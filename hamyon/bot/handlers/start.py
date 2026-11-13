"""Ro'yxatdan o'tish: oila yaratish, taklif havolasi orqali qo'shilish."""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from hamyon.bot import keyboards as kb
from hamyon.bot import texts
from hamyon.bot.sender import notify_family
from hamyon.config import settings
from hamyon.core.text import esc
from hamyon.db.database import Database
from hamyon.services import family as fam

router = Router(name="start")


class Onboard(StatesGroup):
    name = State()
    role = State()


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, state: FSMContext, db: Database,
                    member: dict | None) -> None:
    if member:
        await state.clear()
        await message.answer(f"Qaytganingizdan xursandman, <b>{esc(member['name'])}</b>! 🙂\n"
                             "Harajatni oddiy yozib yuboravering. Qo'llanma: 📖 Yordam tugmasi",
                             reply_markup=kb.main_menu())
        return
    code = (command.args or "").strip()
    if code:
        family = await fam.family_by_invite(db, code)
        if not family:
            await message.answer("❌ Bu taklif havolasi eskirgan yoki noto'g'ri. Oila boshlig'idan yangisini so'rang.")
            return
        await state.update_data(family_id=family["id"], is_admin=False)
    else:
        allowed_owner = settings.owner_tg_id in (None, message.from_user.id)
        if await fam.family_count(db) == 0 and allowed_owner:
            await state.update_data(family_id=None, is_admin=True)
        else:
            await message.answer(texts.NOT_MEMBER)
            return
    await state.set_state(Onboard.name)
    b = InlineKeyboardBuilder()
    if message.from_user.first_name:
        b.button(text=f"✅ {message.from_user.first_name[:30]}", callback_data=kb.NameCb(ok=1))
    await message.answer(texts.ASK_NAME, reply_markup=b.as_markup())


async def _ask_role(message: Message, state: FSMContext, name: str) -> None:
    await state.update_data(name=name)
    await state.set_state(Onboard.role)
    b = InlineKeyboardBuilder()
    for role in fam.ROLES:
        b.button(text=role, callback_data=kb.RoleCb(role=role))
    b.adjust(2)
    await message.answer(texts.ASK_ROLE, reply_markup=b.as_markup())


@router.callback_query(kb.NameCb.filter(), Onboard.name)
async def name_from_profile(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await call.message.edit_reply_markup()
    await _ask_role(call.message, state, (call.from_user.first_name or "Men")[:30])


@router.message(Onboard.name, F.text)
async def name_typed(message: Message, state: FSMContext) -> None:
    name = message.text.strip()
    if not (1 <= len(name) <= 30) or name.startswith("/"):
        await message.answer("Ism 1–30 belgidan iborat bo'lsin. Qaytadan yozing:")
        return
    await _ask_role(message, state, name)


@router.callback_query(kb.RoleCb.filter(), Onboard.role)
async def role_chosen(call: CallbackQuery, callback_data: kb.RoleCb, state: FSMContext, db: Database,
                      bot: Bot) -> None:
    data = await state.get_data()
    await state.clear()
    await call.answer()
    await call.message.edit_reply_markup()
    family_id = data.get("family_id")
    is_admin = bool(data.get("is_admin"))
    if family_id is None:
        if await fam.family_count(db) > 0:  # parallel ikki kishi bosgan holat
            await call.message.answer(texts.NOT_MEMBER)
            return
        family_id = await fam.create_family(db, "Oila")
    member_id = await fam.add_member(db, family_id, call.from_user.id, data["name"], callback_data.role, is_admin)
    member = await fam.get_member(db, member_id)
    await call.message.answer(texts.WELCOME.format(name=esc(data["name"])), reply_markup=kb.main_menu())
    if is_admin:
        family = await fam.get_family(db, family_id)
        me = await bot.get_me()
        link = f"https://t.me/{me.username}?start={family['invite_code']}"
        await call.message.answer(
            "👨‍👩‍👦 <b>Oilangizni qo'shing</b>\nShu havolani onangiz va ukangizga yuboring — ular bosib "
            f"qo'shiladi:\n\n{link}\n\n<i>Havola faqat sizning oilangizga kiritadi. Keyin topish yoki yangilash: "
            "⚙️ Sozlamalar → 🔗 Taklif havolasi</i>")
    else:
        await notify_family(bot, db, member,
                            f"🎉 <b>{esc(member['name'])}</b> ({esc(member['role'])}) oilaviy hisobga qo'shildi!")


# Ro'yxatdan o'tish paytida boshqa har qanday xabar shu yerda qoladi (a'zo talab qiladigan handlerlarga o'tmaydi)
@router.message(Onboard.role)
async def role_expected(message: Message) -> None:
    await message.answer("👆 Iltimos, yuqoridagi tugmalardan birini tanlang.")


@router.message(Onboard.name)
async def name_expected(message: Message) -> None:
    await message.answer("Ismingizni matn bilan yozing (1–30 belgi).")
