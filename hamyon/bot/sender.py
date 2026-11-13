"""Dvigatel javoblarini Telegramga yuborish: tugmalar, xabar bog'lanishi, oilaga xabar berish."""
from __future__ import annotations

import html
import logging
import re

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message, ReplyParameters

from hamyon.bot import keyboards as kb
from hamyon.core.text import chunk
from hamyon.db.database import Database
from hamyon.services import family as fam
from hamyon.services import ledger
from hamyon.services.engine import Reply

log = logging.getLogger(__name__)


def markup_for(reply: Reply):
    if reply.kind == "saved" and reply.batch_id:
        return kb.record_kb(reply.batch_id, with_undo=reply.show_undo)
    if reply.kind == "confirm" and reply.pending_id:
        return kb.confirm_kb(reply.pending_id)
    return None


async def send_text(bot: Bot, chat_id: int, text: str, reply_markup=None, reply_to: int | None = None) -> Message:
    parts = chunk(text)
    sent = None
    for i, part in enumerate(parts):
        last = i == len(parts) - 1
        reply_params = (ReplyParameters(message_id=reply_to, allow_sending_without_reply=True)
                        if reply_to and i == 0 else None)
        markup = reply_markup if last else None
        try:
            sent = await bot.send_message(chat_id, part, reply_markup=markup, reply_parameters=reply_params)
        except TelegramBadRequest as exc:
            if "parse entities" not in str(exc).lower():
                raise
            # HTML buzuq bo'lsa ham xabar yo'qolmasin - teglarsiz oddiy matn
            log.warning("HTML yuborilmadi (%s), oddiy matn sifatida yuboramiz", exc)
            sent = await bot.send_message(chat_id, html.unescape(re.sub(r"</?[a-zA-Z][^>]*>", "", part)),
                                          parse_mode=None, reply_markup=markup)
    return sent


async def deliver(bot: Bot, db: Database, member: dict, chat_id: int, replies: list[Reply],
                  reply_to: int | None = None) -> None:
    family = await fam.get_family(db, member["family_id"])
    for reply in replies:
        sent = await send_text(bot, chat_id, reply.text, markup_for(reply), reply_to)
        reply_to = None
        if sent and (reply.batch_id or reply.pending_id) and reply.kind in ("saved", "confirm"):
            await ledger.link_message(db, chat_id, sent.message_id, reply.batch_id,
                                      reply.tx_ids if reply.kind == "saved" and not reply.show_undo else None,
                                      reply.pending_id)
        if reply.notify_text and family and family["notify_members"]:
            await notify_family(bot, db, member, reply.notify_text)


async def notify_family(bot: Bot, db: Database, author: dict, text: str) -> None:
    for m in await fam.members(db, author["family_id"]):
        if m["id"] == author["id"]:
            continue
        try:
            await bot.send_message(m["tg_id"], text, disable_notification=True)
        except Exception as exc:  # bloklagan, tarmoq, limit - asosiy javobga ta'sir qilmasin
            log.info("%s ga xabar yetmadi: %s", m["name"], exc)


async def broadcast(bot: Bot, db: Database, family_id: int, text: str, reply_markup=None,
                    only_admins: bool = False) -> None:
    for m in await fam.members(db, family_id):
        if only_admins and not m["is_admin"]:
            continue
        try:
            await send_text(bot, m["tg_id"], text, reply_markup)
        except Exception as exc:  # bitta a'zoga yetmasa ham qolganlarga yuboriladi
            log.info("%s ga xabar yetmadi: %s", m["name"], exc)
