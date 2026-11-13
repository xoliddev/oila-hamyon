"""AI ga har so'rovda beriladigan dinamik KONTEKST bloki."""
from __future__ import annotations

from hamyon.core import dates
from hamyon.core.money import fmt
from hamyon.db.database import Database
from hamyon.services import budgets as budgets_svc
from hamyon.services import family as fam
from hamyon.services import ledger
from hamyon.services.family import WALLET_KINDS


async def build_context(db: Database, member: dict) -> str:
    family_id = member["family_id"]
    now = dates.now()
    t = now.date()
    lines = ["=== KONTEKST ==="]
    lines.append(f"Bugun: {t.isoformat()}, {dates.WEEKDAYS[t.weekday()]}. Hozir soat {now:%H:%M} (Toshkent).")
    lines.append(f"Shu oy: {dates.month_start(t).isoformat()} .. {dates.month_end(t).isoformat()}")
    prev_start, prev_end = dates.period_bounds("prev_month", t)
    lines.append(f"O'tgan oy: {prev_start.isoformat()} .. {prev_end.isoformat()}")
    lines.append(f"Shu hafta dushanbasi: {dates.week_start(t).isoformat()}")
    lines.append("So'nggi kunlar (RECENT DAYS):")
    lines.append(dates.recent_days_table(t, 10))

    lines.append("\nOILA A'ZOLARI:")
    for m in await fam.members(db, family_id):
        mark = "  <== YOZAYOTGAN (WRITER)" if m["id"] == member["id"] else ""
        lines.append(f"  - {m['name']} — {m['role'] or 'a`zo'}{mark}")

    lines.append("\nHAMYONLAR (name | turi | valyuta):")
    for w in await fam.wallets(db, family_id):
        flag = " [standart]" if w["is_default"] else ""
        lines.append(f"  - \"{w['name']}\" | {WALLET_KINDS.get(w['kind'], w['kind'])} | {w['currency']}{flag}")
    default = await fam.default_wallet(db, family_id, member)
    if default:
        lines.append(f"  Yozayotgan odamning standart hamyoni: \"{default['name']}\"")

    cats = await fam.categories(db, family_id)
    lines.append("\nCHIQIM KATEGORIYALARI (key — nom — misollar):")
    for c in cats:
        if c["kind"] == "expense":
            lines.append(f"  - {c['key']} — {c['name']} — {c['hints']}")
    lines.append("\nKIRIM KATEGORIYALARI (key — nom — misollar):")
    for c in cats:
        if c["kind"] == "income":
            lines.append(f"  - {c['key']} — {c['name']} — {c['hints']}")

    debts = await ledger.open_debts(db, family_id)
    lines.append("\nOCHIQ QARZLAR (OPEN DEBTS):")
    if debts:
        for d in debts:
            who = "bizga qarzdor (lent)" if d["direction"] == "lent" else "biz qarzdormiz (borrowed)"
            due = f", muddat {d['due_on']}" if d["due_on"] else ""
            lines.append(f"  - {d['counterparty']}: {who}, qoldiq {fmt(d['remaining'], d['currency'])}{due}")
    else:
        lines.append("  (yo'q)")

    budget_rows = await budgets_svc.budget_status(db, family_id)
    if budget_rows:
        lines.append("\nOYLIK LIMITLAR:")
        for b in budget_rows:
            lines.append(f"  - {b['category_name'] or 'Umumiy'}: {fmt(b['amount'])}, ishlatildi {fmt(b['spent'])}")

    recent = await ledger.recent_transactions(db, family_id, limit=8)
    if recent:
        lines.append("\nOXIRGI YOZUVLAR (eng yangisi birinchi):")
        for r in recent:
            lines.append(
                f"  - {r['occurred_on']} {r['kind']} \"{r['description']}\" {fmt(r['amount'], r['currency'])}"
                f" [{r['category_key'] or '-'}] {r['member_name'] or ''}"
            )
    return "\n".join(lines)
