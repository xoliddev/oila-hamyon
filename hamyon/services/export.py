"""Excel eksport: tranzaksiyalar, kategoriyalar, hamyonlar, qarzlar."""
from __future__ import annotations

import asyncio
import io
from datetime import date
from decimal import Decimal

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from hamyon.core import dates
from hamyon.db.database import Database
from hamyon.services import family as fam
from hamyon.services import ledger, reports
from hamyon.services.ledger import KIND_LABEL

HEADER_FILL = PatternFill("solid", fgColor="2E7D6B")
HEADER_FONT = Font(bold=True, color="FFFFFF")
MONEY = '#,##0.00'


def _money(minor: int | None) -> Decimal | None:
    return None if minor is None else Decimal(minor) / 100


def _sheet(wb: Workbook, title: str, headers: list[str], rows: list[list], money_cols: set[int] = frozenset(),
           first: bool = False):
    ws = wb.active if first else wb.create_sheet()
    ws.title = title
    ws.append(headers)
    for cell in ws[1]:
        cell.fill, cell.font = HEADER_FILL, HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center")
    for row in rows:
        ws.append(row)
    for col in money_cols:
        for (cell,) in ws.iter_rows(min_row=2, min_col=col, max_col=col):
            cell.number_format = MONEY
    for i, header in enumerate(headers, 1):
        width = max([len(str(header))] + [len(str(r[i - 1])) for r in rows if r[i - 1] is not None][:500])
        ws.column_dimensions[get_column_letter(i)].width = min(45, max(10, width + 2))
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    return ws


async def build_xlsx(db: Database, family_id: int, start: date, end: date) -> bytes:
    txs = await db.fetchall(
        ledger.TX_SELECT + " WHERE t.family_id=? AND t.deleted_at IS NULL AND t.occurred_on BETWEEN ? AND ?"
                           " ORDER BY t.occurred_on, t.id",
        (family_id, start.isoformat(), end.isoformat()),
    )
    agg = await reports.aggregate(db, family_id, start, end)
    balances = await ledger.wallet_balances(db, family_id)
    wallets = await fam.wallets(db, family_id, include_archived=True)
    debts = await ledger.open_debts(db, family_id)

    def build() -> bytes:
        wb = Workbook()
        tx_rows = []
        for t in txs:
            tx_rows.append([
                t["occurred_on"], KIND_LABEL.get(t["kind"], t["kind"]), t["category_name"], t["description"],
                t["quantity"], t["unit"], _money(t["amount"]), t["currency"],
                _money(t["amount_base"]), t["wallet_name"] or ("Nasiya" if t["on_credit"] else None),
                t["to_wallet_name"], t["member_name"], t["created_by_name"], t["counterparty"], t["id"],
            ])
        _sheet(wb, "Tranzaksiyalar",
               ["Sana", "Turi", "Kategoriya", "Izoh", "Miqdor", "Birlik", "Summa", "Valyuta", "Summa (so'm)",
                "Hamyon", "Qaysi hamyonga", "Kimniki", "Kim yozdi", "Qarshi tomon", "ID"],
               tx_rows, money_cols={7, 9}, first=True)

        cat_rows = [[c["emoji"] + " " + c["name"], "Chiqim" if c["kind"] == "expense" else "Kirim", c["count"],
                     _money(c["amount"])]
                    for c in sorted(agg.by_category.values(), key=lambda c: (c["kind"], -c["amount"]))]
        cat_rows += [[None, None, None, None], ["JAMI CHIQIM", None, agg.expense_count, _money(agg.expense)],
                     ["JAMI KIRIM", None, agg.income_count, _money(agg.income)],
                     ["FARQ", None, None, _money(agg.net)]]
        _sheet(wb, "Kategoriyalar", ["Kategoriya", "Turi", "Soni", "Summa (so'm)"], cat_rows, money_cols={4})

        w_rows = [[w["name"], w["currency"], _money(balances.get(w["id"], 0)), "arxiv" if w["is_archived"] else ""]
                  for w in wallets]
        _sheet(wb, "Hamyonlar", ["Hamyon", "Valyuta", "Qoldiq (hozir)", "Holat"], w_rows, money_cols={3})

        d_rows = [[d["counterparty"], "Bizga qarzdor" if d["direction"] == "lent" else "Biz qarzdormiz",
                   _money(d["amount"]), _money(d["remaining"]), d["currency"], d["opened_on"], d["due_on"]]
                  for d in debts]
        _sheet(wb, "Qarzlar", ["Kim", "Yo'nalish", "Boshlang'ich", "Qoldiq", "Valyuta", "Sana", "Muddat"],
               d_rows, money_cols={3, 4})

        info = wb.create_sheet("Ma'lumot")
        info.append(["Davr", dates.fmt_range(start, end)])
        info.append(["Tayyorlangan", dates.now().strftime("%Y-%m-%d %H:%M")])
        info.append(["Izoh", "Barcha summalar tiyinigacha aniq. 'Summa (so'm)' - MB kursi bo'yicha so'mdagi qiymat."])
        info.column_dimensions["A"].width = 16
        info.column_dimensions["B"].width = 80
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    return await asyncio.to_thread(build)
