"""Hisobotlar: davr bo'yicha yig'indilar, taqqoslash, kunlik va oylik xulosalar."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from hamyon.core import dates
from hamyon.core.money import fmt, fmt_percent, percent
from hamyon.core.text import LINE, bar, esc
from hamyon.db.database import Database
from hamyon.services import budgets as budgets_svc
from hamyon.services import family as fam
from hamyon.services import ledger


@dataclass
class Agg:
    start: date
    end: date
    expense: int = 0
    income: int = 0
    expense_count: int = 0
    income_count: int = 0
    by_category: dict = field(default_factory=dict)      # id -> {name, emoji, kind, amount, count}
    by_member: dict = field(default_factory=dict)        # name -> amount (chiqim)
    income_by_member: dict = field(default_factory=dict)
    by_day: dict = field(default_factory=dict)           # iso -> amount (chiqim)
    by_item: dict = field(default_factory=dict)          # item_key -> {name, amount, count}
    by_wallet: dict = field(default_factory=dict)
    top: list = field(default_factory=list)              # eng katta chiqimlar
    rows: list = field(default_factory=list)

    @property
    def net(self) -> int:
        return self.income - self.expense

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    @property
    def daily_avg(self) -> int:
        """Kunlik o'rtacha chiqim, butun so'mgacha yaxlitlangan (o'rtacha uchun tiyin ma'nosiz)."""
        if not self.days:
            return 0
        return int((Decimal(self.expense) / self.days / 100).quantize(Decimal(1), rounding=ROUND_HALF_UP)) * 100


async def fetch_rows(db: Database, family_id: int, start: date, end: date, *, kinds=("expense", "income"),
                     category_keys: list[str] | None = None, member_ids: list[int] | None = None,
                     search: str | None = None) -> list[dict]:
    sql = ledger.TX_SELECT + " WHERE t.family_id=? AND t.deleted_at IS NULL AND t.occurred_on BETWEEN ? AND ?"
    params: list = [family_id, start.isoformat(), end.isoformat()]
    if kinds:
        sql += f" AND t.kind IN ({','.join('?' * len(kinds))})"
        params += list(kinds)
    if category_keys:
        sql += f" AND c.key IN ({','.join('?' * len(category_keys))})"
        params += list(category_keys)
    if member_ids:
        sql += f" AND t.member_id IN ({','.join('?' * len(member_ids))})"
        params += list(member_ids)
    if search:
        sql += " AND (t.item_key LIKE ? OR LOWER(t.description) LIKE ?)"
        like = f"%{search.lower()}%"
        params += [like, like]
    sql += " ORDER BY t.occurred_on, t.id"
    return await db.fetchall(sql, params)


async def aggregate(db: Database, family_id: int, start: date, end: date, **filters) -> Agg:
    rows = await fetch_rows(db, family_id, start, end, **filters)
    agg = Agg(start=start, end=end, rows=rows)
    for r in rows:
        amt = r["amount_base"]
        cat = agg.by_category.setdefault(r["category_id"], {
            "name": r["category_name"] or "Kategoriyasiz", "emoji": r["category_emoji"] or "•",
            "kind": r["kind"], "amount": 0, "count": 0, "key": r["category_key"]})
        cat["amount"] += amt
        cat["count"] += 1
        member = r["member_name"] or "—"
        if r["kind"] == "expense":
            agg.expense += amt
            agg.expense_count += 1
            agg.by_member[member] = agg.by_member.get(member, 0) + amt
            agg.by_day[r["occurred_on"]] = agg.by_day.get(r["occurred_on"], 0) + amt
            wallet = r["wallet_name"] or ("Nasiya" if r["on_credit"] else "—")
            agg.by_wallet[wallet] = agg.by_wallet.get(wallet, 0) + amt
            if r["item_key"]:
                item = agg.by_item.setdefault(r["item_key"], {"name": r["description"], "amount": 0, "count": 0})
                item["amount"] += amt
                item["count"] += 1
        elif r["kind"] == "income":
            agg.income += amt
            agg.income_count += 1
            agg.income_by_member[member] = agg.income_by_member.get(member, 0) + amt
    agg.top = sorted((r for r in rows if r["kind"] == "expense"), key=lambda r: r["amount_base"], reverse=True)[:5]
    return agg


def previous_period(start: date, end: date) -> tuple[date, date]:
    """Taqqoslash uchun oldingi teng davr. To'liq oy bo'lsa - oldingi oyning shu kunlari."""
    if start.day == 1:
        prev_start = dates.add_months(start, -1)
        span = (end - start).days
        prev_end = min(prev_start + timedelta(days=span), dates.month_end(prev_start))
        return prev_start, prev_end
    length = (end - start).days + 1
    return start - timedelta(days=length), start - timedelta(days=1)


def change_text(now: int, before: int) -> str:
    if before == 0:
        return "yangi" if now else "o'zgarmadi"
    pct = (Decimal(now - before) * 100 / Decimal(before)).quantize(Decimal("0.1"))
    arrow = "📈" if now > before else "📉" if now < before else "➖"
    return f"{arrow} {fmt_percent(pct, signed=True)} ({fmt(now - before, signed=True)})"


async def period_report_text(db: Database, family_id: int, start: date, end: date, title: str | None = None) -> str:
    agg = await aggregate(db, family_id, start, end)
    ps, pe = previous_period(start, end)
    prev = await aggregate(db, family_id, ps, pe)
    head = title or "Hisobot"
    out = [f"📊 <b>{esc(head)}</b> · {dates.fmt_range(start, end)}", ""]
    if not agg.rows:
        out.append("Bu davrda hech qanday kirim-chiqim yozilmagan. 🙂")
        out.append("Harajatni oddiy yozib yuboring: <i>non 6 ming, taksi 18 ming</i>")
        return "\n".join(out)

    out.append(f"💰 Kirim:  <b>{fmt(agg.income)}</b>")
    out.append(f"💸 Chiqim: <b>{fmt(agg.expense)}</b>")
    net_icon = "🟢" if agg.net >= 0 else "🔴"
    saved = f" · tejaldi {fmt_percent(percent(agg.net, agg.income))}" if agg.income > 0 and agg.net > 0 else ""
    out.append(f"{net_icon} Farq:   <b>{fmt(agg.net, signed=True)}</b>{saved}")

    expense_cats = sorted((c for c in agg.by_category.values() if c["kind"] == "expense"),
                          key=lambda c: c["amount"], reverse=True)
    if expense_cats:
        out += ["", "<b>Chiqimlar nimaga ketdi:</b>"]
        for c in expense_cats:
            share = percent(c["amount"], agg.expense)
            out.append(f"{c['emoji']} {esc(c['name'])} — <b>{fmt(c['amount'])}</b> · {fmt_percent(share)}")
            out.append(f"     {bar(share)}")

    income_cats = sorted((c for c in agg.by_category.values() if c["kind"] == "income"),
                         key=lambda c: c["amount"], reverse=True)
    if income_cats:
        out += ["", "<b>Kirim manbalari:</b>"]
        for c in income_cats:
            out.append(f"{c['emoji']} {esc(c['name'])} — <b>{fmt(c['amount'])}</b>")

    if len(agg.by_member) > 1:
        out += ["", "<b>Kim qancha sarfladi:</b>"]
        for name, amt in sorted(agg.by_member.items(), key=lambda x: x[1], reverse=True):
            out.append(f"👤 {esc(name)} — {fmt(amt)} · {fmt_percent(percent(amt, agg.expense))}")

    if agg.top:
        out += ["", "<b>Eng katta chiqimlar:</b>"]
        for i, r in enumerate(agg.top, 1):
            d = date.fromisoformat(r["occurred_on"])
            out.append(f"{i}. {dates.fmt_short(d)} {esc(r['description'])} — {fmt(r['amount_base'])}")

    if agg.expense and agg.days > 1:
        out += ["", f"📅 Kunlik o'rtacha chiqim: <b>{fmt(agg.daily_avg)}</b>"]
    if prev.rows:
        out.append(f"↕️ Oldingi davrga ({dates.fmt_range(ps, pe)}) nisbatan chiqim: {change_text(agg.expense, prev.expense)}")
    return "\n".join(out)


async def daily_digest_text(db: Database, family_id: int, day: date) -> str | None:
    agg = await aggregate(db, family_id, day, day)
    month = await aggregate(db, family_id, dates.month_start(day), day)
    out = [f"🌙 <b>Kun yakuni</b> · {dates.fmt_date(day)}, {dates.WEEKDAYS[day.weekday()]}", ""]
    if not agg.rows:
        out.append("Bugun hech narsa yozilmadi. Hammasi yozildimi? 🙂")
        out.append("Esdan chiqqan harajat bo'lsa, hozir yozib qo'ying.")
    else:
        by_member: dict[str, list[dict]] = defaultdict(list)
        for r in agg.rows:
            by_member[r["member_name"] or "—"].append(r)
        for name, rows in by_member.items():
            out.append(f"👤 <b>{esc(name)}</b>")
            for r in rows:
                sign = "−" if r["kind"] == "expense" else "+"
                out.append(f"   {r['category_emoji'] or '•'} {esc(r['description'])} {sign}{fmt(r['amount_base'])}")
        out += [LINE, f"💸 Bugungi chiqim: <b>{fmt(agg.expense)}</b>"]
        if agg.income:
            out.append(f"💰 Bugungi kirim: <b>{fmt(agg.income)}</b>")
    out.append(f"🗓 Oy boshidan chiqim: <b>{fmt(month.expense)}</b>")
    if month.days > 1 and month.expense:
        out.append(f"   kuniga o'rtacha {fmt(month.daily_avg)}")
    for b in await budgets_svc.budget_status(db, family_id, day):
        if b["pct"] >= 80:
            out.append(f"⚠️ {esc(b['category_name'] or 'Umumiy limit')}: {fmt_percent(b['pct'])} ishlatildi")
    debts = await ledger.open_debts(db, family_id)
    due_soon = [d for d in debts if d["due_on"] and date.fromisoformat(d["due_on"]) <= day + timedelta(days=3)]
    for d in due_soon:
        who = "qaytarishi kerak" if d["direction"] == "lent" else "ga qaytarishimiz kerak"
        out.append(f"⏰ {esc(d['counterparty'])} {who}: {fmt(d['remaining'], d['currency'])} ({d['due_on']})")
    return "\n".join(out)


async def insight_facts(db: Database, family_id: int, start: date, end: date) -> dict:
    """Hisobchi xulosasi uchun AI ga beriladigan aniq faktlar."""
    agg = await aggregate(db, family_id, start, end)
    ps, pe = previous_period(start, end)
    prev = await aggregate(db, family_id, ps, pe)
    cats = sorted((c for c in agg.by_category.values() if c["kind"] == "expense"), key=lambda c: -c["amount"])
    prev_by_key = {c["key"]: c["amount"] for c in prev.by_category.values() if c["kind"] == "expense"}
    facts = {
        "period": dates.fmt_range(start, end),
        "expense_total": fmt(agg.expense), "income_total": fmt(agg.income),
        "net": fmt(agg.net, signed=True),
        "savings_rate": fmt_percent(percent(agg.net, agg.income)) if agg.income else None,
        "previous_period": dates.fmt_range(ps, pe),
        "previous_expense_total": fmt(prev.expense),
        "expense_change": change_text(agg.expense, prev.expense) if prev.rows else None,
        "categories": [
            {"name": c["name"], "amount": fmt(c["amount"]), "share": fmt_percent(percent(c["amount"], agg.expense)),
             "vs_previous": change_text(c["amount"], prev_by_key.get(c["key"], 0)) if prev.rows else None}
            for c in cats[:8]
        ],
        "by_member": {k: fmt(v) for k, v in agg.by_member.items()},
        "largest_expenses": [{"date": r["occurred_on"], "what": r["description"], "amount": fmt(r["amount_base"])}
                             for r in agg.top],
        "daily_average": fmt(agg.daily_avg) if agg.days else None,
        "budgets": [{"category": b["category_name"] or "Umumiy", "limit": fmt(b["amount"]), "spent": fmt(b["spent"]),
                     "used": fmt_percent(b["pct"])} for b in await budgets_svc.budget_status(db, family_id, end)],
        "open_debts": [{"who": d["counterparty"], "direction": "bizga qarzdor" if d["direction"] == "lent" else "biz qarzdormiz",
                        "remaining": fmt(d["remaining"], d["currency"]), "due": d["due_on"]}
                       for d in await ledger.open_debts(db, family_id)],
        "price_changes": await price_changes(db, family_id, start, end),
    }
    return facts


async def price_changes(db: Database, family_id: int, start: date, end: date) -> list[dict]:
    """Davr ichida narxi o'zgargan muntazam mahsulotlar."""
    rows = await db.fetchall(
        """SELECT item_key, description, amount, quantity, unit, currency, occurred_on FROM transactions
           WHERE family_id=? AND kind='expense' AND deleted_at IS NULL AND item_key IS NOT NULL
             AND occurred_on <= ? ORDER BY occurred_on, id""",
        (family_id, end.isoformat()),
    )
    history: dict[tuple, list] = defaultdict(list)
    for r in rows:
        qty = Decimal(r["quantity"]) if r["quantity"] else Decimal(1)
        if qty <= 0:
            continue
        unit_price = int(Decimal(r["amount"]) / qty)
        unit = (r["unit"] or "").lower()
        unit = "" if unit in ("ta", "dona", "shtuk", "sht") else unit
        history[(r["item_key"], unit, r["currency"])].append((r["occurred_on"], unit_price, r["description"]))
    out = []
    for (key, unit, cur), hist in history.items():
        in_period = [h for h in hist if h[0] >= start.isoformat()]
        before = [h for h in hist if h[0] < start.isoformat()]
        if not in_period or not before:
            continue
        old, new = before[-1][1], in_period[-1][1]
        if old and old != new and abs(percent(new - old, old)) <= 60:
            out.append({"item": in_period[-1][2], "unit": unit or "dona", "was": fmt(old, cur), "now": fmt(new, cur),
                        "change": fmt_percent(percent(new - old, old), signed=True)})
    return out[:8]


async def wallets_text(db: Database, family_id: int) -> tuple[str, int]:
    """Hamyonlar qoldig'i va so'mdagi umumiy summa."""
    from hamyon.services.currency import RateUnavailable, get_rate
    balances = await ledger.wallet_balances(db, family_id)
    total_uzs = 0
    lines = ["💼 <b>Hamyonlar</b>", ""]
    for w in await fam.wallets(db, family_id):
        bal = balances.get(w["id"], 0)
        star = " ⭐" if w["is_default"] else ""
        kind = fam.WALLET_KINDS.get(w["kind"], "👛").split()[0]
        line = f"{kind} {esc(w['name'])}{star}: <b>{fmt(bal, w['currency'])}</b>"
        if w["currency"] != "UZS":
            try:
                rate = await get_rate(db, w["currency"], dates.today())
                uzs = int(Decimal(bal) * rate)
                total_uzs += uzs
                line += f"  <i>≈ {fmt(uzs)}</i>"
            except RateUnavailable:
                line += "  <i>(kurs noma'lum)</i>"
        else:
            total_uzs += bal
        if bal < 0:
            line += "  ⚠️"
        lines.append(line)
    lines += [LINE, f"Jami: <b>{fmt(total_uzs)}</b>"]
    return "\n".join(lines), total_uzs
