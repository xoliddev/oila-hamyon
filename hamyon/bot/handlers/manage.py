"""Boshqaruv: hamyonlar, kategoriyalar, sozlamalar."""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from hamyon.bot import keyboards as kb
from hamyon.bot import texts
from hamyon.bot.handlers.commands import cmd_family, cmd_invite
from hamyon.core.text import esc
from hamyon.db.database import Database
from hamyon.services import family as fam
from hamyon.services import ledger, reports

router = Router(name="manage")


class NewWallet(StatesGroup):
    name = State()


class NewCategory(StatesGroup):
    name = State()
    hints = State()


# ================================================================== hamyonlar
async def _wallets_view(db: Database, member: dict) -> tuple[str, object]:
    text, _ = await reports.wallets_text(db, member["family_id"])
    b = InlineKeyboardBuilder()
    wallets = await fam.wallets(db, member["family_id"])
    for w in wallets:
        if not w["is_default"]:
            b.button(text=f"⭐ {w['name'][:16]} — asosiy", callback_data=kb.WalletCb(action="default", wid=w["id"]))
        if len(wallets) > 1:
            b.button(text=f"🗄 {w['name'][:16]} — arxiv", callback_data=kb.WalletCb(action="archive", wid=w["id"]))
    b.button(text="➕ Yangi hamyon", callback_data=kb.WalletCb(action="add", wid=0))
    b.adjust(2)
    text += ("\n\n⭐ — oilaning asosiy hamyoni (hamyon aytilmasa shunga yoziladi).\n"
             "<i>O'zingizning shaxsiy asosiy hamyoningizni ⚙️ Sozlamalar → 👛 Mening hamyonim orqali tanlaysiz.</i>")
    return text, b.as_markup()


@router.message(Command("hamyonlar"))
async def cmd_wallets(message: Message, db: Database, member: dict) -> None:
    text, markup = await _wallets_view(db, member)
    await message.answer(text, reply_markup=markup)


@router.callback_query(kb.WalletCb.filter())
async def wallet_cb(call: CallbackQuery, callback_data: kb.WalletCb, db: Database, member: dict,
                    state: FSMContext) -> None:
    family_id = member["family_id"]
    if callback_data.action == "add":
        await call.answer()
        await state.set_state(NewWallet.name)
        await call.message.answer("👛 Yangi hamyon nomini yozing (masalan: <i>Humo karta</i>, <i>Jamg'arma</i>, "
                                  "<i>Onamning kartasi</i>):", reply_markup=kb.cancel_kb())
        return
    wallet = await fam.get_wallet(db, callback_data.wid)
    if not wallet or wallet["family_id"] != family_id:
        await call.answer("Topilmadi", show_alert=True)
        return
    if callback_data.action == "default":
        await fam.set_default_wallet(db, family_id, wallet["id"])
        await call.answer(f"{wallet['name']} endi asosiy")
    elif callback_data.action == "archive":
        balance = (await ledger.wallet_balances(db, family_id)).get(wallet["id"], 0)
        if balance != 0:
            await call.answer("Qoldig'i nol bo'lmagan hamyonni arxivlab bo'lmaydi. Avval pulini boshqa hamyonga "
                              "o'tkazing yoki qoldiqni to'g'rilang.", show_alert=True)
            return
        await fam.archive_wallet(db, family_id, wallet["id"])
        remaining = await fam.wallets(db, family_id)
        if remaining and not any(w["is_default"] for w in remaining):
            await fam.set_default_wallet(db, family_id, remaining[0]["id"])
        await call.answer("Arxivlandi")
    text, markup = await _wallets_view(db, member)
    await call.message.edit_text(text, reply_markup=markup)


@router.message(NewWallet.name, F.text)
async def wallet_name(message: Message, state: FSMContext, db: Database, member: dict) -> None:
    name = message.text.strip()
    if not (1 <= len(name) <= 30) or name.startswith("/") or name in texts.MENU_BUTTONS:
        await message.answer("Nom 1–30 belgi bo'lsin. Qaytadan yozing:", reply_markup=kb.cancel_kb())
        return
    if any(w["name"].lower() == name.lower() for w in await fam.wallets(db, member["family_id"], True)):
        await message.answer("Bunday nomli hamyon bor. Boshqa nom yozing:", reply_markup=kb.cancel_kb())
        return
    await state.update_data(wallet_name=name)
    await state.set_state(None)  # keyingi qadamlar tugma orqali; ma'lumot saqlanib qoladi
    b = InlineKeyboardBuilder()
    for cur in ("UZS", "USD", "EUR", "RUB"):
        b.button(text=cur, callback_data=kb.NewWalletCb(field="cur", value=cur))
    b.adjust(4)
    await message.answer(f"«{esc(name)}» qaysi valyutada?", reply_markup=b.as_markup())


@router.callback_query(kb.NewWalletCb.filter(F.field == "cur"))
async def wallet_currency(call: CallbackQuery, callback_data: kb.NewWalletCb, state: FSMContext) -> None:
    await state.update_data(wallet_currency=callback_data.value)
    b = InlineKeyboardBuilder()
    for key, label in fam.WALLET_KINDS.items():
        b.button(text=label, callback_data=kb.NewWalletCb(field="kind", value=key))
    b.adjust(2)
    await call.answer()
    await call.message.edit_text("Turi qanday?", reply_markup=b.as_markup())


@router.callback_query(kb.NewWalletCb.filter(F.field == "kind"))
async def wallet_kind(call: CallbackQuery, callback_data: kb.NewWalletCb, state: FSMContext, db: Database,
                      member: dict) -> None:
    data = await state.get_data()
    await state.clear()
    name = data.get("wallet_name")
    if not name:
        await call.answer("Qaytadan boshlang: ⚙️ Sozlamalar → 👛 Hamyonlar", show_alert=True)
        return
    await fam.add_wallet(db, member["family_id"], name, callback_data.value, data.get("wallet_currency", "UZS"))
    await call.answer("Qo'shildi")
    await call.message.edit_text(
        f"✅ <b>{esc(name)}</b> hamyoni qo'shildi.\n\nEndi undagi pulni yozing, masalan:\n"
        f"<i>{esc(name)}da 1 200 000 bor</i>")


@router.message(Command("bekor_qilish"))
async def cancel_state(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Bekor qilindi.", reply_markup=kb.main_menu())


@router.callback_query(kb.CancelCb.filter())
async def cancel_state_btn(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.answer("Bekor qilindi")
    await call.message.edit_text(call.message.html_text + "\n\n❌ <i>Bekor qilindi</i>")


# ================================================================== kategoriyalar
@router.message(Command("kategoriyalar"))
async def cmd_categories(message: Message, db: Database, member: dict) -> None:
    cats = await fam.categories(db, member["family_id"])
    lines = ["🗂 <b>Kategoriyalar</b>", "", "<b>Chiqim:</b>"]
    lines += [f"{c['emoji']} {esc(c['name'])}" for c in cats if c["kind"] == "expense"]
    lines += ["", "<b>Kirim:</b>"]
    lines += [f"{c['emoji']} {esc(c['name'])}" for c in cats if c["kind"] == "income"]
    lines += ["", "<i>Kategoriyani o'zim tanlayman. Kerakli kategoriya bo'lmasa — qo'shing.</i>"]
    b = InlineKeyboardBuilder()
    b.button(text="➕ Chiqim kategoriyasi", callback_data=kb.CatCb(action="add_expense", cid=0))
    b.button(text="➕ Kirim kategoriyasi", callback_data=kb.CatCb(action="add_income", cid=0))
    b.button(text="🗄 Kategoriyani o'chirish", callback_data=kb.CatCb(action="archive_menu", cid=0))
    b.adjust(2, 1)
    await message.answer("\n".join(lines), reply_markup=b.as_markup())


@router.callback_query(kb.CatCb.filter())
async def category_cb(call: CallbackQuery, callback_data: kb.CatCb, state: FSMContext, db: Database,
                      member: dict) -> None:
    if callback_data.action in ("add_expense", "add_income"):
        await state.set_state(NewCategory.name)
        await state.update_data(cat_kind="expense" if callback_data.action == "add_expense" else "income")
        await call.answer()
        await call.message.answer("Kategoriya nomini yozing. Boshida emoji qo'yishingiz mumkin, masalan:\n"
                                  "<i>🐈 Mushuk uchun</i> yoki <i>🚗 Mashina krediti</i>", reply_markup=kb.cancel_kb())
        return
    if callback_data.action == "archive_menu":
        b = InlineKeyboardBuilder()
        for c in await fam.categories(db, member["family_id"]):
            if c["key"] not in ("boshqa_chiqim", "boshqa_kirim"):
                b.button(text=f"{c['emoji']} {c['name'][:22]}", callback_data=kb.CatCb(action="archive", cid=c["id"]))
        b.adjust(2)
        await call.answer()
        await call.message.answer("Qaysi kategoriyani o'chiramiz? (eski yozuvlar o'zgarmaydi)",
                                  reply_markup=b.as_markup())
        return
    if callback_data.action == "archive":
        await fam.archive_category(db, member["family_id"], callback_data.cid)
        await call.answer("O'chirildi")
        await call.message.edit_reply_markup()
    if callback_data.action == "no_hints":
        await call.answer()
        await call.message.edit_reply_markup()
        await _finish_category(call.message, state, db, member, "")


@router.message(NewCategory.name, F.text)
async def category_name(message: Message, state: FSMContext) -> None:
    raw = message.text.strip()
    if not (2 <= len(raw) <= 40) or raw.startswith("/"):
        await message.answer("Nom 2–40 belgi bo'lsin. Qaytadan yozing:", reply_markup=kb.cancel_kb())
        return
    emoji, name = "•", raw
    first = raw.split(maxsplit=1)
    if len(first) == 2 and not first[0][0].isalnum():
        emoji, name = first[0], first[1]
    await state.update_data(cat_name=name, cat_emoji=emoji)
    await state.set_state(NewCategory.hints)
    skip = InlineKeyboardBuilder()
    skip.button(text="⏭ Misolsiz qo'shish", callback_data=kb.CatCb(action="no_hints", cid=0))
    skip.button(text="❌ Bekor qilish", callback_data=kb.CancelCb(what="fsm"))
    await message.answer("Bu kategoriyaga nimalar kiradi? Bir nechta misol yozing — men shunga qarab tanlayman.\n"
                         "Masalan: <i>mushuk ovqati, veterinar, qum</i>", reply_markup=skip.as_markup())


@router.message(NewCategory.hints, F.text)
async def category_hints(message: Message, state: FSMContext, db: Database, member: dict) -> None:
    hints = "" if message.text.strip() == "-" else message.text.strip()[:300]
    await _finish_category(message, state, db, member, hints)


async def _finish_category(message: Message, state: FSMContext, db: Database, member: dict, hints: str) -> None:
    data = await state.get_data()
    await state.clear()
    if not data.get("cat_name"):
        await message.answer("Qaytadan boshlang: ⚙️ Sozlamalar → 🗂 Kategoriyalar")
        return
    await fam.add_category(db, member["family_id"], data["cat_name"], data["cat_emoji"], data["cat_kind"], hints)
    await message.answer(f"✅ {esc(data['cat_emoji'])} <b>{esc(data['cat_name'])}</b> kategoriyasi qo'shildi.",
                         reply_markup=kb.main_menu())


# ================================================================== sozlamalar
async def _settings_view(db: Database, member: dict) -> tuple[str, object]:
    family = await fam.get_family(db, member["family_id"])
    me = await fam.get_member(db, member["id"])
    my_wallet = await fam.default_wallet(db, member["family_id"], me)
    on = lambda v: "✅" if v else "❌"  # noqa: E731
    text = ("⚙️ <b>Sozlamalar</b>\n\n"
            f"🌙 Kunlik xulosa: {on(family['daily_report'])} · soat {family['daily_report_time']}\n"
            f"🗓 Oylik hisobot (har oy 1-sanasi): {on(family['monthly_report'])}\n"
            f"🔔 Yozuvlarni oilaga ko'rsatish: {on(family['notify_members'])}\n"
            f"👛 Mening asosiy hamyonim: <b>{esc(my_wallet['name']) if my_wallet else '—'}</b>\n\n"
            "<i>Tugmani bosib o'zgartiring.</i>")
    b = InlineKeyboardBuilder()
    b.button(text=f"{on(family['daily_report'])} Kunlik xulosa", callback_data=kb.SetCb(key="daily"))
    b.button(text=f"🕘 Vaqt: {family['daily_report_time']}", callback_data=kb.SetCb(key="time"))
    b.button(text=f"{on(family['monthly_report'])} Oylik hisobot", callback_data=kb.SetCb(key="monthly"))
    b.button(text=f"{on(family['notify_members'])} Oilaga ko'rsatish", callback_data=kb.SetCb(key="notify"))
    b.button(text="👛 Mening hamyonim", callback_data=kb.SetCb(key="mywallet"))
    b.button(text="💼 Hamyonlar", callback_data=kb.SetCb(key="wallets"))
    b.button(text="🗂 Kategoriyalar", callback_data=kb.SetCb(key="cats"))
    b.button(text="👨‍👩‍👦 Oila a'zolari", callback_data=kb.SetCb(key="family"))
    if member["is_admin"]:
        b.button(text="🔗 Taklif havolasi", callback_data=kb.SetCb(key="invite"))
    b.adjust(2, 2, 1, 2, 2)
    return text, b.as_markup()


@router.message(Command("sozlamalar"))
@router.message(F.text == texts.BTN_SETTINGS)
async def cmd_settings(message: Message, db: Database, member: dict) -> None:
    text, markup = await _settings_view(db, member)
    await message.answer(text, reply_markup=markup)


TIMES = ["20:00", "21:00", "22:00", "23:00"]


@router.callback_query(kb.SetCb.filter())
async def settings_cb(call: CallbackQuery, callback_data: kb.SetCb, db: Database, member: dict, bot: Bot) -> None:
    family = await fam.get_family(db, member["family_id"])
    key = callback_data.key
    # Bo'limlarga o'tish - yangi xabar sifatida ochiladi
    sections = {
        "wallets": lambda: cmd_wallets(call.message, db, member),
        "cats": lambda: cmd_categories(call.message, db, member),
        "family": lambda: cmd_family(call.message, db, member),
        "invite": lambda: cmd_invite(call.message, db, member, bot),
    }
    if key in sections:
        await call.answer()
        await sections[key]()
        return
    if key == "daily":
        await fam.update_family(db, family["id"], daily_report=0 if family["daily_report"] else 1)
    elif key == "monthly":
        await fam.update_family(db, family["id"], monthly_report=0 if family["monthly_report"] else 1)
    elif key == "notify":
        await fam.update_family(db, family["id"], notify_members=0 if family["notify_members"] else 1)
    elif key == "time":
        cur = family["daily_report_time"]
        nxt = TIMES[(TIMES.index(cur) + 1) % len(TIMES)] if cur in TIMES else TIMES[1]
        await fam.update_family(db, family["id"], daily_report_time=nxt)
    elif key == "mywallet":
        wallets = await fam.wallets(db, family["id"])
        me = await fam.get_member(db, member["id"])
        current = await fam.default_wallet(db, family["id"], me)
        ids = [w["id"] for w in wallets]
        if current and current["id"] in ids:
            nxt = wallets[(ids.index(current["id"]) + 1) % len(wallets)]
        else:
            nxt = wallets[0]
        await fam.update_member(db, member["id"], default_wallet_id=nxt["id"])
    await call.answer("Saqlandi")
    text, markup = await _settings_view(db, member)
    await call.message.edit_text(text, reply_markup=markup)
