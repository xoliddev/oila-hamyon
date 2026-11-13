"""Erkin kiritish: matn, ovoz, chek rasmi, hujjat va javob (reply) orqali tuzatish.

Bu router eng oxirida ulanadi - buyruq va menyu tugmalari undan oldin ushlanadi.
"""
from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, ForceReply, Message
from aiogram.utils.chat_action import ChatActionSender

from hamyon.bot import keyboards as kb
from hamyon.bot.middlewares import RateLimiter
from hamyon.bot.sender import deliver
from hamyon.config import settings
from hamyon.db.database import Database
from hamyon.services import ledger
from hamyon.services.engine import Engine

log = logging.getLogger(__name__)
router = Router(name="input")
limiter = RateLimiter(settings.ai_rate_per_minute)

MAX_VOICE_SECONDS = 300
MAX_FILE_BYTES = 15 * 1024 * 1024
EDIT_PROMPT = ("✏️ Nimani tuzatamiz? <b>Shu xabarga javob qilib</b> yozing, masalan:\n"
               "<i>15 ming edi</i> · <i>kartadan to'laganman</i> · <i>kecha bo'lgan</i> · "
               "<i>ikkinchisini o'chir</i> · <i>bu onamniki</i>")


async def _guard(message: Message) -> bool:
    if not limiter.allow(message.from_user.id):
        await message.answer("⏳ Juda tez yozyapsiz — bir daqiqa kutib, keyin davom eting.")
        return False
    return True


async def _bot_link(db: Database, message: Message, bot: Bot) -> dict | None:
    """Foydalanuvchi bot xabariga javob yozgan bo'lsa - o'sha xabar bog'langan yozuv."""
    target = message.reply_to_message
    if not target or not target.from_user or target.from_user.id != bot.id:
        return None
    return await ledger.resolve_message(db, message.chat.id, target.message_id)


@router.message(F.text & ~F.text.startswith("/"))
async def on_text(message: Message, bot: Bot, db: Database, engine: Engine, member: dict,
                  state: FSMContext) -> None:
    await state.clear()  # tugallanmay qolgan oqim (masalan, hamyon qo'shish) va eski ma'lumotlari bekor
    text = message.text.strip()
    if len(text) > 2000:
        await message.answer("Xabar juda uzun. Iltimos, qisqaroq qilib bo'lib yuboring.")
        return
    if not await _guard(message):
        return
    link = await _bot_link(db, message, bot)
    async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
        if link:
            replies = await engine.correct(member, link, text)
        else:
            replies = await engine.handle(member, text=text)
    await deliver(bot, db, member, message.chat.id, replies, reply_to=message.message_id)


@router.message(F.voice | F.audio)
async def on_voice(message: Message, bot: Bot, db: Database, engine: Engine, member: dict) -> None:
    media = message.voice or message.audio
    if (media.duration or 0) > MAX_VOICE_SECONDS:
        await message.answer("🎙 Ovozli xabar 5 daqiqadan oshmasin.")
        return
    if (media.file_size or 0) > MAX_FILE_BYTES:
        await message.answer("Fayl juda katta.")
        return
    if not await _guard(message):
        return
    async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
        buf = await bot.download(media)
        mime = getattr(media, "mime_type", None) or "audio/ogg"
        replies = await engine.handle(member, text=message.caption, audio=buf.getvalue(), audio_mime=mime)
    await deliver(bot, db, member, message.chat.id, replies, reply_to=message.message_id)


@router.message(F.photo | (F.document & F.document.mime_type.regexp(r"^(image/|application/pdf)")))
async def on_photo(message: Message, bot: Bot, db: Database, engine: Engine, member: dict) -> None:
    if message.photo:
        media, mime = message.photo[-1], "image/jpeg"
    else:
        media, mime = message.document, message.document.mime_type
    if (media.file_size or 0) > MAX_FILE_BYTES:
        await message.answer("Fayl juda katta (15 MB dan oshmasin).")
        return
    if not await _guard(message):
        return
    await message.answer("🧾 Chekni o'qiyapman, har bir qatorini tekshiraman...")
    async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
        buf = await bot.download(media)
        replies = await engine.handle(member, text=message.caption, image=buf.getvalue(), image_mime=mime)
    await deliver(bot, db, member, message.chat.id, replies, reply_to=message.message_id)


@router.message(F.video | F.video_note | F.sticker | F.animation | F.location | F.contact)
async def on_other(message: Message) -> None:
    await message.answer("Men matn, ovozli xabar va chek rasmini tushunaman 🙂")


# ------------------------------------------------------------------ yozuv tugmalari
@router.callback_query(kb.RecCb.filter())
async def record_cb(call: CallbackQuery, callback_data: kb.RecCb, bot: Bot, db: Database, member: dict) -> None:
    family_id = member["family_id"]
    batch = await db.fetchone("SELECT * FROM batches WHERE id=? AND family_id=?", (callback_data.batch_id, family_id))
    if not batch:
        await call.answer("Topilmadi", show_alert=True)
        return
    if callback_data.action == "undo":
        count = await ledger.delete_batch(db, family_id, batch["id"])
        await call.answer("Bekor qilindi" if count else "Allaqachon bekor qilingan")
        try:
            await call.message.edit_text(call.message.html_text + "\n\n↩️ <i>Bekor qilindi</i>",
                                         reply_markup=kb.redo_kb(batch["id"]))
        except Exception:
            await call.message.edit_reply_markup(reply_markup=kb.redo_kb(batch["id"]))
    elif callback_data.action == "redo":
        await ledger.restore_batch(db, family_id, batch["id"])
        await call.answer("Qaytarildi")
        original = call.message.html_text
        text = original.replace("\n\n↩️ <i>Bekor qilindi</i>", "")
        if text == original:  # /bekor buyrug'i xabari
            text = original.replace("↩️ Bekor qilindi", "🔄 Qaytarildi", 1)
        try:
            await call.message.edit_text(text, reply_markup=kb.record_kb(batch["id"]))
        except Exception:
            await call.message.edit_reply_markup(reply_markup=kb.record_kb(batch["id"]))
    elif callback_data.action == "edit":
        await call.answer()
        link = await ledger.resolve_message(db, call.message.chat.id, call.message.message_id)
        prompt = await call.message.reply(EDIT_PROMPT, reply_markup=ForceReply(selective=True,
                                          input_field_placeholder="masalan: 15 ming edi"))
        await ledger.link_message(db, prompt.chat.id, prompt.message_id, batch["id"],
                                  link["tx_id_list"] if link else None)


@router.callback_query(kb.PendCb.filter())
async def pending_cb(call: CallbackQuery, callback_data: kb.PendCb, bot: Bot, db: Database, engine: Engine,
                     member: dict) -> None:
    if callback_data.action == "ok":
        await call.answer("Saqlanyapti...")
        await call.message.edit_reply_markup()
        reply = await engine.confirm_pending(member, callback_data.pid)
        await deliver(bot, db, member, call.message.chat.id, [reply])
    elif callback_data.action == "no":
        if await engine.cancel_pending(member, callback_data.pid):
            await call.answer("Bekor qilindi")
            await call.message.edit_text(call.message.html_text + "\n\n❌ <i>Saqlanmadi</i>")
        else:
            await call.answer("Bu yozuv allaqachon saqlangan yoki bekor qilingan.", show_alert=True)
            await call.message.edit_reply_markup()
    elif callback_data.action == "edit":
        await call.answer()
        prompt = await call.message.reply(EDIT_PROMPT, reply_markup=ForceReply(selective=True))
        await ledger.link_message(db, prompt.chat.id, prompt.message_id, None, None, callback_data.pid)


@router.callback_query(kb.TxCb.filter())
async def tx_cb(call: CallbackQuery, callback_data: kb.TxCb, db: Database, member: dict) -> None:
    rows = await ledger.transactions_by_ids(db, member["family_id"], [callback_data.tx_id])
    if not rows:
        await call.answer("Allaqachon o'chirilgan", show_alert=True)
        return
    t = rows[0]
    if callback_data.action == "del":
        await ledger.delete_transactions(db, member["family_id"], [t["id"]])
        await call.answer("O'chirildi")
        await call.message.edit_text(call.message.html_text + "\n\n🗑 <i>O'chirildi</i>")
    elif callback_data.action == "edit":
        await call.answer()
        prompt = await call.message.reply(EDIT_PROMPT, reply_markup=ForceReply(selective=True))
        await ledger.link_message(db, prompt.chat.id, prompt.message_id, t["batch_id"], [t["id"]])
