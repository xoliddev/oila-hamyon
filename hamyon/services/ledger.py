"""Bosh kitob: yozuvlarni atomar saqlash, o'chirish, hamyon qoldiqlari va qarzlar.

Buxgalteriya qoidalari:
  * expense / income            -> oila daromad-xarajat hisobotiga kiradi
  * transfer                    -> faqat hamyonlar orasida, hisobotga kirmaydi
  * debt_*                      -> pul harakati bor, lekin bu xarajat/daromad emas
  * nasiya (on_credit) expense  -> xarajat bor, hamyondan pul chiqmaydi, qarz ochiladi
  * adjustment                  -> hamyon qoldig'ini haqiqiyga tenglash (hisobotga kirmaydi)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from hamyon.core import dates
from hamyon.db.database import Database, Tx

# Hamyonga ta'sir ishorasi (wallet_id tomonidan)
WALLET_SIGN = {
    "expense": -1, "income": +1, "transfer": -1,
    "debt_give": -1, "debt_take": +1, "debt_repay_in": +1, "debt_repay_out": -1,
    "adjustment": +1,  # wallet_amount ishorali saqlanadi
}

KIND_LABEL = {
    "expense": "Chiqim", "income": "Kirim", "transfer": "O'tkazma",
    "debt_give": "Qarz berildi", "debt_take": "Qarz olindi",
    "debt_repay_in": "Qarz qaytdi", "debt_repay_out": "Qarz to'landi",
    "adjustment": "Qoldiq tuzatildi",
}

KIND_EMOJI = {
    "transfer": "🔁", "debt_give": "📤", "debt_take": "📥",
    "debt_repay_in": "✅", "debt_repay_out": "✅", "adjustment": "⚖️",
}


@dataclass
class Op:
    """AI natijasidan tekshirilgan, hisoblangan, saqlashga tayyor amal."""
    kind: str
    amount: int
    currency: str
    rate: Decimal
    amount_base: int
    occurred_on: date
    member_id: int | None
    description: str
    wallet_id: int | None = None
    wallet_amount: int | None = None
    to_wallet_id: int | None = None
    to_wallet_amount: int | None = None
    category_id: int | None = None
    item_key: str | None = None
    quantity: str | None = None
    unit: str | None = None
    counterparty: str | None = None
    on_credit: bool = False
    due_on: date | None = None
    debt_id: int | None = None
    # ko'rsatish uchun
    category_key: str = ""
    category_name: str = ""
    category_emoji: str = ""
    wallet_name: str = ""
    wallet_currency: str = "UZS"
    to_wallet_name: str = ""
    to_wallet_currency: str = "UZS"
    member_name: str = ""
    note: str | None = None
    warnings: list[str] = field(default_factory=list)
    suspicious: bool = False
    # balance_set uchun
    target_balance: int | None = None
    current_balance: int | None = None

    def to_json(self) -> dict:
        data = {k: v for k, v in self.__dict__.items()}
        data["rate"] = str(self.rate)
        data["occurred_on"] = self.occurred_on.isoformat()
        data["due_on"] = self.due_on.isoformat() if self.due_on else None
        return data

    @classmethod
    def from_json(cls, data: dict) -> "Op":
        data = dict(data)
        data["rate"] = Decimal(data["rate"])
        data["occurred_on"] = date.fromisoformat(data["occurred_on"])
        data["due_on"] = date.fromisoformat(data["due_on"]) if data.get("due_on") else None
        return cls(**data)


# ---------------------------------------------------------------- saqlash

async def _insert_tx(tx: Tx, family_id: int, batch_id: int, created_by: int | None, op: Op) -> int:
    return await tx.execute(
        """INSERT INTO transactions
           (family_id, batch_id, kind, amount, currency, rate, amount_base, wallet_id, wallet_amount,
            to_wallet_id, to_wallet_amount, category_id, member_id, created_by, description, item_key,
            quantity, unit, counterparty, debt_id, on_credit, occurred_on)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (family_id, batch_id, op.kind, op.amount, op.currency, str(op.rate), op.amount_base,
         op.wallet_id, op.wallet_amount, op.to_wallet_id, op.to_wallet_amount, op.category_id,
         op.member_id, created_by, op.description, op.item_key, op.quantity, op.unit,
         op.counterparty, op.debt_id, int(op.on_credit), op.occurred_on.isoformat()),
    )


async def _open_debt(tx: Tx, family_id: int, origin_tx_id: int, direction: str, op: Op) -> int:
    debt_id = await tx.execute(
        """INSERT INTO debts (family_id, origin_tx_id, direction, counterparty, amount, currency,
                              member_id, opened_on, due_on, note)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (family_id, origin_tx_id, direction, op.counterparty or op.description, op.amount, op.currency,
         op.member_id, op.occurred_on.isoformat(), op.due_on.isoformat() if op.due_on else None,
         op.description),
    )
    await tx.execute("UPDATE transactions SET debt_id=? WHERE id=?", (debt_id, origin_tx_id))
    return debt_id


async def _write_ops(tx: Tx, family_id: int, batch_id: int, created_by: int | None, ops: list[Op]) -> list[int]:
    ids: list[int] = []
    touched_debts: set[int] = set()
    for op in ops:
        if op.kind == "adjustment" and not op.wallet_amount:
            continue  # qoldiq to'g'ri - yozuv kerak emas
        tx_id = await _insert_tx(tx, family_id, batch_id, created_by, op)
        ids.append(tx_id)
        if op.kind == "debt_give":
            await _open_debt(tx, family_id, tx_id, "lent", op)
        elif op.kind == "debt_take":
            await _open_debt(tx, family_id, tx_id, "borrowed", op)
        elif op.kind == "expense" and op.on_credit:
            await _open_debt(tx, family_id, tx_id, "borrowed", op)
        elif op.kind in ("debt_repay_in", "debt_repay_out") and op.debt_id:
            touched_debts.add(op.debt_id)
    for debt_id in touched_debts:
        await refresh_debt_status(tx, debt_id)
    return ids


async def save_batch(db: Database, *, family_id: int, member_id: int | None, source: str,
                     raw_text: str | None, transcript: str | None, ops: list[Op]) -> tuple[int, list[int]]:
    async with db.transaction() as tx:
        batch_id = await tx.execute(
            "INSERT INTO batches (family_id, member_id, source, raw_text, transcript) VALUES (?,?,?,?,?)",
            (family_id, member_id, source, (raw_text or "")[:2000], (transcript or "")[:2000] or None),
        )
        ids = await _write_ops(tx, family_id, batch_id, member_id, ops)
    return batch_id, ids


async def _soft_delete(tx: Tx, family_id: int, tx_ids: list[int]) -> None:
    if not tx_ids:
        return
    marks = ",".join("?" * len(tx_ids))
    rows = await tx.fetchall(
        f"SELECT id, kind, debt_id FROM transactions WHERE family_id=? AND id IN ({marks}) AND deleted_at IS NULL",
        (family_id, *tx_ids),
    )
    now = dates.now().isoformat(timespec="seconds")
    for row in rows:
        await tx.execute("UPDATE transactions SET deleted_at=? WHERE id=?", (now, row["id"]))
        # shu yozuv ochgan qarz bo'lsa - qarz ham o'chadi
        await tx.execute("UPDATE debts SET deleted_at=? WHERE origin_tx_id=? AND deleted_at IS NULL", (now, row["id"]))
        if row["debt_id"] and row["kind"] in ("debt_repay_in", "debt_repay_out"):
            await refresh_debt_status(tx, row["debt_id"])


async def delete_transactions(db: Database, family_id: int, tx_ids: list[int]) -> int:
    async with db.transaction() as tx:
        await _soft_delete(tx, family_id, tx_ids)
    return len(tx_ids)


async def delete_batch(db: Database, family_id: int, batch_id: int) -> int:
    rows = await db.fetchall(
        "SELECT id FROM transactions WHERE family_id=? AND batch_id=? AND deleted_at IS NULL", (family_id, batch_id)
    )
    ids = [r["id"] for r in rows]
    async with db.transaction() as tx:
        await _soft_delete(tx, family_id, ids)
        await tx.execute("UPDATE batches SET deleted_at=? WHERE id=?",
                         (dates.now().isoformat(timespec="seconds"), batch_id))
    return len(ids)


async def replace_transactions(db: Database, family_id: int, batch_id: int, old_ids: list[int],
                               created_by: int | None, ops: list[Op]) -> list[int]:
    """Tuzatish: eski yozuvlarni o'chirib, yangilarini o'sha paketga atomar yozadi."""
    async with db.transaction() as tx:
        await _soft_delete(tx, family_id, old_ids)
        return await _write_ops(tx, family_id, batch_id, created_by, ops)


async def restore_batch(db: Database, family_id: int, batch_id: int) -> None:
    async with db.transaction() as tx:
        await tx.execute("UPDATE transactions SET deleted_at=NULL WHERE family_id=? AND batch_id=?", (family_id, batch_id))
        await tx.execute(
            "UPDATE debts SET deleted_at=NULL WHERE origin_tx_id IN (SELECT id FROM transactions WHERE batch_id=?)",
            (batch_id,),
        )
        await tx.execute("UPDATE batches SET deleted_at=NULL WHERE id=?", (batch_id,))


# ---------------------------------------------------------------- qoldiqlar

async def wallet_balances(db: Database, family_id: int) -> dict[int, int]:
    balances: dict[int, int] = {}
    rows = await db.fetchall(
        """SELECT wallet_id, kind, SUM(wallet_amount) AS s FROM transactions
           WHERE family_id=? AND deleted_at IS NULL AND wallet_id IS NOT NULL GROUP BY wallet_id, kind""",
        (family_id,),
    )
    for r in rows:
        balances[r["wallet_id"]] = balances.get(r["wallet_id"], 0) + WALLET_SIGN[r["kind"]] * (r["s"] or 0)
    rows = await db.fetchall(
        """SELECT to_wallet_id, SUM(to_wallet_amount) AS s FROM transactions
           WHERE family_id=? AND deleted_at IS NULL AND to_wallet_id IS NOT NULL GROUP BY to_wallet_id""",
        (family_id,),
    )
    for r in rows:
        balances[r["to_wallet_id"]] = balances.get(r["to_wallet_id"], 0) + (r["s"] or 0)
    return balances


async def wallet_balance(db: Database, family_id: int, wallet_id: int) -> int:
    return (await wallet_balances(db, family_id)).get(wallet_id, 0)


# ---------------------------------------------------------------- qarzlar

def _repaid_in_debt_currency(debt: dict, rows: list[dict]) -> int:
    debt_rate = Decimal(debt.get("origin_rate") or "1")
    total = 0
    for r in rows:
        if r["currency"] == debt["currency"]:
            total += r["amount"]
        else:
            total += int((Decimal(r["amount_base"]) / debt_rate).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    return total


async def _debt_with_rate(conn, debt_id: int) -> dict | None:
    return await conn.fetchone(
        """SELECT d.*, t.rate AS origin_rate FROM debts d LEFT JOIN transactions t ON t.id = d.origin_tx_id
           WHERE d.id=?""", (debt_id,))


async def debt_remaining(conn, debt: dict) -> int:
    rows = await conn.fetchall(
        """SELECT amount, currency, amount_base FROM transactions
           WHERE debt_id=? AND kind IN ('debt_repay_in','debt_repay_out') AND deleted_at IS NULL""",
        (debt["id"],),
    )
    return debt["amount"] - _repaid_in_debt_currency(debt, rows)


async def refresh_debt_status(conn, debt_id: int) -> None:
    debt = await _debt_with_rate(conn, debt_id)
    if not debt:
        return
    remaining = await debt_remaining(conn, debt)
    if remaining <= 0 and not debt["closed_at"]:
        await conn.execute("UPDATE debts SET closed_at=? WHERE id=?", (dates.now().isoformat(timespec="seconds"), debt_id))
    elif remaining > 0 and debt["closed_at"]:
        await conn.execute("UPDATE debts SET closed_at=NULL WHERE id=?", (debt_id,))


async def open_debts(db: Database, family_id: int) -> list[dict]:
    rows = await db.fetchall(
        """SELECT d.*, t.rate AS origin_rate FROM debts d LEFT JOIN transactions t ON t.id = d.origin_tx_id
           WHERE d.family_id=? AND d.deleted_at IS NULL AND d.closed_at IS NULL
           ORDER BY d.due_on IS NULL, d.due_on, d.opened_on""",
        (family_id,),
    )
    for r in rows:
        r["remaining"] = await debt_remaining(db, r)
    return [r for r in rows if r["remaining"] > 0]


async def get_debt(db: Database, family_id: int, debt_id: int) -> dict | None:
    debt = await db.fetchone(
        """SELECT d.*, t.rate AS origin_rate FROM debts d LEFT JOIN transactions t ON t.id = d.origin_tx_id
           WHERE d.id=? AND d.family_id=? AND d.deleted_at IS NULL""", (debt_id, family_id))
    if debt:
        debt["remaining"] = await debt_remaining(db, debt)
    return debt


# ---------------------------------------------------------------- o'qish

TX_SELECT = """
SELECT t.*, c.name AS category_name, c.emoji AS category_emoji, c.key AS category_key,
       w.name AS wallet_name, w.currency AS wallet_currency,
       tw.name AS to_wallet_name, tw.currency AS to_wallet_currency,
       m.name AS member_name, cb.name AS created_by_name
FROM transactions t
LEFT JOIN categories c ON c.id = t.category_id
LEFT JOIN wallets w ON w.id = t.wallet_id
LEFT JOIN wallets tw ON tw.id = t.to_wallet_id
LEFT JOIN members m ON m.id = t.member_id
LEFT JOIN members cb ON cb.id = t.created_by
"""


async def transactions_by_ids(db: Database, family_id: int, ids: list[int]) -> list[dict]:
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    return await db.fetchall(
        TX_SELECT + f" WHERE t.family_id=? AND t.id IN ({marks}) AND t.deleted_at IS NULL ORDER BY t.id",
        (family_id, *ids),
    )


async def batch_transactions(db: Database, family_id: int, batch_id: int) -> list[dict]:
    return await db.fetchall(
        TX_SELECT + " WHERE t.family_id=? AND t.batch_id=? AND t.deleted_at IS NULL ORDER BY t.id",
        (family_id, batch_id),
    )


async def recent_transactions(db: Database, family_id: int, limit: int = 20, offset: int = 0) -> list[dict]:
    return await db.fetchall(
        TX_SELECT + " WHERE t.family_id=? AND t.deleted_at IS NULL ORDER BY t.occurred_on DESC, t.id DESC LIMIT ? OFFSET ?",
        (family_id, limit, offset),
    )


async def last_batch(db: Database, family_id: int, member_id: int) -> dict | None:
    return await db.fetchone(
        """SELECT b.* FROM batches b WHERE b.family_id=? AND b.member_id=? AND b.deleted_at IS NULL
           AND EXISTS (SELECT 1 FROM transactions t WHERE t.batch_id=b.id AND t.deleted_at IS NULL)
           ORDER BY b.id DESC LIMIT 1""",
        (family_id, member_id),
    )


async def last_price(db: Database, family_id: int, item_key: str, exclude_batch: int | None = None) -> dict | None:
    """Mahsulotning oldingi narxi (narx o'zgarishini aytish uchun)."""
    return await db.fetchone(
        """SELECT amount, currency, quantity, unit, occurred_on FROM transactions
           WHERE family_id=? AND item_key=? AND kind='expense' AND deleted_at IS NULL AND IFNULL(batch_id,0)<>?
           ORDER BY occurred_on DESC, id DESC LIMIT 1""",
        (family_id, item_key, exclude_batch or 0),
    )


# ---------------------------------------------------------------- xabar bog'lanishlari

async def link_message(db: Database, chat_id: int, message_id: int, batch_id: int | None,
                       tx_ids: list[int] | None = None, pending_id: int | None = None) -> None:
    await db.execute(
        "INSERT OR REPLACE INTO message_links (chat_id, message_id, batch_id, tx_ids, pending_id) VALUES (?,?,?,?,?)",
        (chat_id, message_id, batch_id, ",".join(map(str, tx_ids)) if tx_ids else None, pending_id),
    )


async def resolve_message(db: Database, chat_id: int, message_id: int) -> dict | None:
    row = await db.fetchone("SELECT * FROM message_links WHERE chat_id=? AND message_id=?", (chat_id, message_id))
    if row:
        row["tx_id_list"] = [int(x) for x in (row["tx_ids"] or "").split(",") if x]
    return row
