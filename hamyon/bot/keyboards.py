"""Tugmalar va callback ma'lumotlari."""
from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

from hamyon.bot import texts
from hamyon.core.dates import PERIODS


class RecCb(CallbackData, prefix="r"):
    action: str        # undo | redo | edit
    batch_id: int


class PendCb(CallbackData, prefix="p"):
    action: str        # ok | no | edit
    pid: int


class TxCb(CallbackData, prefix="t"):
    action: str        # del | edit
    tx_id: int


class HistCb(CallbackData, prefix="h"):
    offset: int


class RepCb(CallbackData, prefix="rep"):
    action: str        # show | chart | xlsx | insight
    period: str


class DebtCb(CallbackData, prefix="d"):
    action: str        # close
    debt_id: int


class RecurCb(CallbackData, prefix="rc"):
    action: str        # paid | skip | del
    rid: int


class WalletCb(CallbackData, prefix="w"):
    action: str        # default | archive | add | mine
    wid: int


class NewWalletCb(CallbackData, prefix="nw"):
    field: str         # cur | kind
    value: str


class CatCb(CallbackData, prefix="c"):
    action: str        # add_expense | add_income | archive_menu | archive
    cid: int


class SetCb(CallbackData, prefix="s"):
    key: str


class MemCb(CallbackData, prefix="m"):
    action: str        # off | invite | newlink
    mid: int


class BudCb(CallbackData, prefix="b"):
    action: str        # del
    bid: int


class RoleCb(CallbackData, prefix="role"):
    role: str


class NameCb(CallbackData, prefix="nm"):
    ok: int


class CancelCb(CallbackData, prefix="x"):
    what: str


def main_menu() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardBuilder()
    for b in (texts.BTN_REPORT, texts.BTN_BALANCE, texts.BTN_HISTORY, texts.BTN_DEBTS, texts.BTN_BUDGET,
              texts.BTN_RECURRING, texts.BTN_UNDO, texts.BTN_SETTINGS, texts.BTN_HELP):
        kb.button(text=b)
    kb.adjust(2, 2, 2, 1, 2)
    return kb.as_markup(resize_keyboard=True, is_persistent=True,
                        input_field_placeholder="Masalan: non 6 ming, taksi 18 ming")


def cancel_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="❌ Bekor qilish", callback_data=CancelCb(what="fsm"))
    return kb.as_markup()


def record_kb(batch_id: int, with_undo: bool = True) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if with_undo:
        kb.button(text="↩️ Bekor qilish", callback_data=RecCb(action="undo", batch_id=batch_id))
    kb.button(text="✏️ Tuzatish", callback_data=RecCb(action="edit", batch_id=batch_id))
    return kb.as_markup()


def redo_kb(batch_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔄 Qaytarish", callback_data=RecCb(action="redo", batch_id=batch_id))
    return kb.as_markup()


def confirm_kb(pid: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ To'g'ri, saqlash", callback_data=PendCb(action="ok", pid=pid))
    kb.button(text="❌ Bekor", callback_data=PendCb(action="no", pid=pid))
    kb.button(text="✏️ Tuzatish", callback_data=PendCb(action="edit", pid=pid))
    kb.adjust(2, 1)
    return kb.as_markup()


def tx_kb(tx_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✏️ Tuzatish", callback_data=TxCb(action="edit", tx_id=tx_id))
    kb.button(text="🗑 O'chirish", callback_data=TxCb(action="del", tx_id=tx_id))
    return kb.as_markup()


def periods_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for key, label in PERIODS.items():
        kb.button(text=label, callback_data=RepCb(action="show", period=key))
    kb.adjust(2)
    return kb.as_markup()


def report_actions_kb(period: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📈 Diagramma", callback_data=RepCb(action="chart", period=period))
    kb.button(text="🧠 Hisobchi xulosasi", callback_data=RepCb(action="insight", period=period))
    kb.button(text="📥 Excel", callback_data=RepCb(action="xlsx", period=period))
    kb.button(text="🗓 Boshqa davr", callback_data=RepCb(action="menu", period=period))
    kb.adjust(2, 2)
    return kb.as_markup()


def history_kb(tx_ids: list[int], offset: int, has_more: bool) -> InlineKeyboardMarkup:
    """Har bir yozuv uchun raqamli tugma (bosilsa - batafsil) va sahifalash."""
    kb = InlineKeyboardBuilder()
    for i, tx_id in enumerate(tx_ids, 1):
        kb.button(text=str(offset + i), callback_data=TxCb(action="view", tx_id=tx_id))
    sizes = [5] * (len(tx_ids) // 5) + ([len(tx_ids) % 5] if len(tx_ids) % 5 else [])
    nav = 0
    if offset > 0:
        kb.button(text="◀️ Yangiroq", callback_data=HistCb(offset=max(0, offset - 15)))
        nav += 1
    if has_more:
        kb.button(text="Eskiroq ▶️", callback_data=HistCb(offset=offset + 15))
        nav += 1
    kb.adjust(*(sizes + ([nav] if nav else [])))
    return kb.as_markup()


def recurring_due_kb(rid: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ To'landi — yozib qo'y", callback_data=RecurCb(action="paid", rid=rid))
    kb.button(text="⏭ Bu oy o'tkazib yubor", callback_data=RecurCb(action="skip", rid=rid))
    kb.adjust(1)
    return kb.as_markup()
