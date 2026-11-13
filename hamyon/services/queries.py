"""Savollarga javob: hamma sonlarni kod hisoblaydi, AI faqat chiroyli jumla tuzadi."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from hamyon.ai.schemas import QuerySpec
from hamyon.core import dates
from hamyon.core.money import fmt, fmt_decimal, fmt_percent, percent
from hamyon.core.text import esc
from hamyon.db.database import Database
from hamyon.services import budgets as budgets_svc
from hamyon.services import family as fam
from hamyon.services import ledger, reports


def _period(spec: QuerySpec) -> tuple[date, date]:
    t = dates.today()
    start = dates.parse_date(spec.date_from)
    end = dates.parse_date(spec.date_to)
    if spec.focus == "prices" and not start:
        start = t - timedelta(days=365)
    start = start or dates.month_start(t)
    end = end or t
    if end > t:
        end = t
    if start > end:
        start, end = end, start
    return start, end


async def run(db: Database, family_id: int, spec: QuerySpec) -> dict:
    facts: dict = {"bugun": dates.today().isoformat()}

    if spec.focus == "balances":
        text, total = await reports.wallets_text(db, family_id)
        balances = await ledger.wallet_balances(db, family_id)
        facts["wallets"] = [{"name": w["name"], "balance": fmt(balances.get(w["id"], 0), w["currency"])}
                            for w in await fam.wallets(db, family_id)]
        facts["total_in_uzs"] = fmt(total)
        return facts

    if spec.focus == "debts":
        debts = await ledger.open_debts(db, family_id)
        lent = [d for d in debts if d["direction"] == "lent"]
        borrowed = [d for d in debts if d["direction"] == "borrowed"]
        facts["they_owe_us"] = [{"who": d["counterparty"], "remaining": fmt(d["remaining"], d["currency"]),
                                 "original": fmt(d["amount"], d["currency"]), "since": d["opened_on"],
                                 "due": d["due_on"]} for d in lent]
        facts["we_owe"] = [{"who": d["counterparty"], "remaining": fmt(d["remaining"], d["currency"]),
                            "original": fmt(d["amount"], d["currency"]), "since": d["opened_on"],
                            "due": d["due_on"]} for d in borrowed]
        facts["they_owe_us_total_uzs"] = fmt(sum(d["remaining"] for d in lent if d["currency"] == "UZS"))
        facts["we_owe_total_uzs"] = fmt(sum(d["remaining"] for d in borrowed if d["currency"] == "UZS"))
        return facts

    if spec.focus == "budgets":
        rows = await budgets_svc.budget_status(db, family_id)
        facts["budgets"] = [{"category": b["category_name"] or "Umumiy oylik limit", "limit": fmt(b["amount"]),
                             "spent": fmt(b["spent"]), "used": fmt_percent(b["pct"]),
                             "left": fmt(b["left"]), "forecast_month_end": fmt(b["forecast"])} for b in rows]
        if not rows:
            facts["note"] = "Hali birorta limit qo'yilmagan."
        return facts

    start, end = _period(spec)
    members = await fam.members(db, family_id, active_only=False)
    member_ids = []
    for name in spec.members or []:
        m = fam.match_by_name(members, name)
        if m:
            member_ids.append(m["id"])
    cats = await fam.categories(db, family_id)
    cat_keys = [c for c in (spec.categories or []) if any(x["key"] == c for x in cats)]
    search = (spec.search or "").strip().lower() or None
    kinds = ("income",) if spec.focus == "income" else ("expense",) if spec.focus in ("expense", "prices") \
        else ("expense", "income")

    agg = await reports.aggregate(db, family_id, start, end, kinds=kinds, category_keys=cat_keys or None,
                                  member_ids=member_ids or None, search=search)
    facts.update({
        "period": dates.fmt_range(start, end), "date_from": start.isoformat(), "date_to": end.isoformat(),
        "days_in_period": agg.days,
        "filters": {
            "categories": [c["name"] for c in cats if c["key"] in cat_keys],
            "members": [m["name"] for m in members if m["id"] in member_ids],
            "search": search,
        },
        "expense_total": fmt(agg.expense), "expense_count": agg.expense_count,
        "income_total": fmt(agg.income), "income_count": agg.income_count,
    })
    if "income" in kinds and "expense" in kinds:
        facts["net_income_minus_expense"] = fmt(agg.net, signed=True)
        if agg.income:
            facts["savings_rate"] = fmt_percent(percent(agg.net, agg.income))
    if agg.expense and agg.days > 1:
        facts["daily_average_expense"] = fmt(agg.daily_avg)

    group = spec.group_by
    total_for_share = agg.expense or agg.income
    if group in ("category", "none") or group is None:
        facts["by_category"] = [
            {"name": c["name"], "kind": c["kind"], "amount": fmt(c["amount"]), "count": c["count"],
             "share": fmt_percent(percent(c["amount"], agg.expense if c["kind"] == "expense" else agg.income))}
            for c in sorted(agg.by_category.values(), key=lambda c: -c["amount"])
        ]
    if group == "member" or len(agg.by_member) > 1:
        facts["expense_by_member"] = [{"name": k, "amount": fmt(v), "share": fmt_percent(percent(v, agg.expense))}
                                      for k, v in sorted(agg.by_member.items(), key=lambda x: -x[1])]
        if agg.income_by_member:
            facts["income_by_member"] = {k: fmt(v) for k, v in agg.income_by_member.items()}
    if group == "day":
        facts["expense_by_day"] = {d: fmt(v) for d, v in sorted(agg.by_day.items())}
    if group == "month":
        months: dict[str, int] = {}
        for r in agg.rows:
            if r["kind"] == "expense":
                months[r["occurred_on"][:7]] = months.get(r["occurred_on"][:7], 0) + r["amount_base"]
        facts["expense_by_month"] = {k: fmt(v) for k, v in sorted(months.items())}
    if group == "item":
        facts["by_item"] = [{"item": v["name"], "amount": fmt(v["amount"]), "times": v["count"]}
                            for v in sorted(agg.by_item.values(), key=lambda v: -v["amount"])[:15]]
    if group == "wallet":
        facts["by_wallet"] = {k: fmt(v) for k, v in agg.by_wallet.items()}
    if total_for_share:
        facts["largest"] = [{"date": r["occurred_on"], "what": r["description"], "amount": fmt(r["amount_base"]),
                             "who": r["member_name"]} for r in agg.top]

    if spec.focus in ("transactions", "prices") or search:
        items = []
        for r in agg.rows[-25:]:
            item = {"date": r["occurred_on"], "what": r["description"], "amount": fmt(r["amount"], r["currency"]),
                    "who": r["member_name"], "category": r["category_name"]}
            if r["quantity"]:
                qty = Decimal(r["quantity"])
                item["quantity"] = f"{fmt_decimal(qty)} {r['unit'] or ''}".strip()
                if qty > 0:
                    item["unit_price"] = fmt(int(Decimal(r["amount"]) / qty), r["currency"])
            items.append(item)
        facts["entries"] = items
        facts["entries_note"] = "eng oxirgi 25 tasi, eskidan yangiga" if len(agg.rows) > 25 else "hammasi"

    if spec.compare_from and spec.compare_to:
        cs, ce = dates.parse_date(spec.compare_from), dates.parse_date(spec.compare_to)
        if cs and ce:
            prev = await reports.aggregate(db, family_id, min(cs, ce), max(cs, ce), kinds=kinds,
                                           category_keys=cat_keys or None, member_ids=member_ids or None, search=search)
            prev_cats = {c["key"]: c["amount"] for c in prev.by_category.values()}
            facts["comparison"] = {
                "period": dates.fmt_range(min(cs, ce), max(cs, ce)),
                "expense_total": fmt(prev.expense), "income_total": fmt(prev.income),
                "expense_change": reports.change_text(agg.expense, prev.expense),
                "income_change": reports.change_text(agg.income, prev.income) if prev.income or agg.income else None,
                "by_category_change": [
                    {"name": c["name"], "now": fmt(c["amount"]), "before": fmt(prev_cats.get(c["key"], 0)),
                     "change": reports.change_text(c["amount"], prev_cats.get(c["key"], 0))}
                    for c in sorted(agg.by_category.values(), key=lambda c: -c["amount"])[:8]
                ],
            }
    if not agg.rows:
        facts["no_data"] = True
    return facts


def fallback_text(facts: dict) -> str:
    """AI ishlamay qolsa - faktlarning o'zini ko'rsatamiz."""
    lines = ["📋 <b>Natija</b>"]
    if "period" in facts:
        lines.append(f"Davr: {esc(facts['period'])}")
    for key, label in (("expense_total", "Chiqim"), ("income_total", "Kirim"),
                       ("net_income_minus_expense", "Farq"), ("total_in_uzs", "Jami")):
        if facts.get(key):
            lines.append(f"{label}: <b>{esc(facts[key])}</b>")
    for c in facts.get("by_category", [])[:10]:
        lines.append(f"• {esc(c['name'])}: {esc(c['amount'])} ({esc(c['share'])})")
    for w in facts.get("wallets", []):
        lines.append(f"• {esc(w['name'])}: {esc(w['balance'])}")
    for d in facts.get("they_owe_us", []):
        lines.append(f"• {esc(d['who'])} bizga: {esc(d['remaining'])}")
    for d in facts.get("we_owe", []):
        lines.append(f"• Biz {esc(d['who'])}ga: {esc(d['remaining'])}")
    for e in facts.get("entries", [])[-10:]:
        lines.append(f"• {esc(e['date'])} {esc(e['what'])}: {esc(e['amount'])}")
    return "\n".join(lines)
