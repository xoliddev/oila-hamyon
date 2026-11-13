"""Oylik byudjet (limit) va takroriy to'lovlar."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from hamyon.core import dates
from hamyon.core.money import fmt, fmt_percent, percent
from hamyon.core.text import bar, esc
from hamyon.db.database import Database


async def set_budget(db: Database, family_id: int, category_id: int | None, amount: int) -> None:
    if amount <= 0:
        await db.execute(
            "DELETE FROM budgets WHERE family_id=? AND IFNULL(category_id,0)=IFNULL(?,0)", (family_id, category_id)
        )
        return
    existing = await db.fetchone(
        "SELECT id FROM budgets WHERE family_id=? AND IFNULL(category_id,0)=IFNULL(?,0)", (family_id, category_id)
    )
    if existing:
        await db.execute("UPDATE budgets SET amount=? WHERE id=?", (amount, existing["id"]))
    else:
        await db.execute("INSERT INTO budgets (family_id, category_id, amount) VALUES (?,?,?)",
                         (family_id, category_id, amount))


async def delete_budget(db: Database, family_id: int, budget_id: int) -> None:
    await db.execute("DELETE FROM budgets WHERE id=? AND family_id=?", (budget_id, family_id))


async def budget_status(db: Database, family_id: int, ref: date | None = None) -> list[dict]:
    """Har bir limit uchun shu oy ishlatilgan summa."""
    ref = ref or dates.today()
    start, end = dates.month_start(ref), dates.month_end(ref)
    rows = await db.fetchall(
        """SELECT b.id, b.category_id, b.amount, c.name AS category_name, c.emoji
           FROM budgets b LEFT JOIN categories c ON c.id=b.category_id
           WHERE b.family_id=? ORDER BY b.category_id IS NOT NULL, c.sort""",
        (family_id,),
    )
    for r in rows:
        params: list = [family_id, start.isoformat(), end.isoformat()]
        sql = """SELECT IFNULL(SUM(amount_base),0) FROM transactions WHERE family_id=? AND kind='expense'
                 AND deleted_at IS NULL AND occurred_on BETWEEN ? AND ?"""
        if r["category_id"]:
            sql += " AND category_id=?"
            params.append(r["category_id"])
        r["spent"] = await db.scalar(sql, params, default=0)
        r["pct"] = percent(r["spent"], r["amount"])
        r["left"] = r["amount"] - r["spent"]
        days_total = (end - start).days + 1
        days_passed = (ref - start).days + 1
        # Shu sur'atda davom etsa oy oxirigacha prognoz
        r["forecast"] = int(Decimal(r["spent"]) * days_total / days_passed) if days_passed else r["spent"]
        r["days_left"] = days_total - days_passed
    return rows


def render_budget_line(r: dict) -> str:
    name = f"{r['emoji']} {esc(r['category_name'])}" if r["category_id"] else "🧮 <b>Umumiy oylik limit</b>"
    icon = "🔴" if r["pct"] >= 100 else "🟠" if r["pct"] >= 80 else "🟢"
    lines = [
        f"{icon} {name}",
        f"   {bar(r['pct'])} {fmt_percent(r['pct'])}",
        f"   {fmt(r['spent'])} / {fmt(r['amount'])}",
    ]
    if r["left"] >= 0:
        per_day = r["left"] // max(1, r["days_left"] + 1)
        lines.append(f"   Qoldi: <b>{fmt(r['left'])}</b> · kuniga ~{fmt(per_day // 100 * 100)}")
    else:
        lines.append(f"   ⚠️ Limitdan oshdi: <b>{fmt(-r['left'])}</b>")
    if r["left"] >= 0 and r["forecast"] > r["amount"]:
        lines.append(f"   📈 Shu sur'atda oy oxiriga ~{fmt(r['forecast'] // 100000 * 100000)} bo'ladi")
    return "\n".join(lines)


async def check_alerts(db: Database, family_id: int, category_ids: set[int | None]) -> list[str]:
    """Yangi yozuvdan keyin 80% / 100% chegarasi kesib o'tilganini aniqlaydi (har oy bir martadan)."""
    if not category_ids:
        return []
    period = dates.today().strftime("%Y-%m")
    alerts = []
    for r in await budget_status(db, family_id):
        if r["category_id"] is not None and r["category_id"] not in category_ids:
            continue
        for level in (100, 80):
            if r["pct"] >= level:
                done = await db.fetchone(
                    "SELECT 1 FROM budget_alerts WHERE budget_id=? AND period=? AND level=?", (r["id"], period, level)
                )
                if not done:
                    await db.execute("INSERT OR IGNORE INTO budget_alerts VALUES (?,?,?)", (r["id"], period, level))
                    if level == 100:
                        await db.execute("INSERT OR IGNORE INTO budget_alerts VALUES (?,?,?)", (r["id"], period, 80))
                    name = r["category_name"] or "Umumiy limit"
                    if level == 100:
                        alerts.append(f"🔴 <b>{esc(name)}</b> limiti tugadi: {fmt(r['spent'])} / {fmt(r['amount'])}")
                    else:
                        alerts.append(f"🟠 <b>{esc(name)}</b> limitining {fmt_percent(r['pct'])} ishlatildi "
                                      f"(qoldi {fmt(r['left'])})")
                break
    return alerts


# ---------------------------------------------------------------- takroriy to'lovlar

def next_due_date(day_of_month: int, ref: date) -> date:
    candidate = dates.add_months(ref.replace(day=1), 0, day_of_month)
    if candidate < ref:
        candidate = dates.add_months(ref.replace(day=1), 1, day_of_month)
    return candidate


async def add_recurring(db: Database, family_id: int, *, kind: str, description: str, amount: int, currency: str,
                        category_id: int | None, wallet_id: int | None, member_id: int | None,
                        day_of_month: int) -> int:
    day_of_month = max(1, min(31, int(day_of_month)))
    due = next_due_date(day_of_month, dates.today())
    return await db.execute(
        """INSERT INTO recurring (family_id, kind, description, amount, currency, category_id, wallet_id,
                                  member_id, day_of_month, next_due) VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (family_id, kind, description, amount, currency, category_id, wallet_id, member_id, day_of_month,
         due.isoformat()),
    )


async def list_recurring(db: Database, family_id: int) -> list[dict]:
    return await db.fetchall(
        """SELECT r.*, c.emoji, c.name AS category_name FROM recurring r LEFT JOIN categories c ON c.id=r.category_id
           WHERE r.family_id=? AND r.is_active=1 ORDER BY r.day_of_month""", (family_id,))


async def get_recurring(db: Database, family_id: int, rec_id: int) -> dict | None:
    return await db.fetchone("SELECT * FROM recurring WHERE id=? AND family_id=?", (rec_id, family_id))


async def claim_recurring(db: Database, rec: dict, today: date) -> bool:
    """Muddati kelgan to'lovni atomar ravishda keyingi oyga suradi. Allaqachon surilgan bo'lsa False."""
    current = date.fromisoformat(rec["next_due"])
    nxt = dates.add_months(current.replace(day=1), 1, rec["day_of_month"])
    changed = await db.execute_rowcount(
        "UPDATE recurring SET next_due=?, last_reminded=NULL WHERE id=? AND next_due=? AND next_due<=?",
        (nxt.isoformat(), rec["id"], rec["next_due"], today.isoformat()),
    )
    return changed == 1


async def unclaim_recurring(db: Database, rec: dict) -> None:
    await db.execute("UPDATE recurring SET next_due=? WHERE id=?", (rec["next_due"], rec["id"]))


async def deactivate_recurring(db: Database, family_id: int, rec_id: int) -> None:
    await db.execute("UPDATE recurring SET is_active=0 WHERE id=? AND family_id=?", (rec_id, family_id))
