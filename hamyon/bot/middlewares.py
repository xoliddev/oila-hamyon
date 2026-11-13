"""Ruxsat: bot faqat oila a'zolari uchun. Begonalar faqat taklif havolasi bilan kira oladi."""
from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from hamyon.bot import texts
from hamyon.db.database import Database
from hamyon.services import family as fam

log = logging.getLogger(__name__)


class AuthMiddleware(BaseMiddleware):
    async def __call__(self, handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
                       event: TelegramObject, data: dict[str, Any]) -> Any:
        db: Database = data["db"]
        user = data.get("event_from_user")
        if not user or user.is_bot:
            return None
        member = await fam.member_by_tg(db, user.id)
        data["member"] = member
        if member:
            # Buyruq yoki menyu tugmasi har qanday tugallanmagan oqimni (hamyon/kategoriya qo'shish) to'xtatadi
            if isinstance(event, Message) and event.text and (
                    event.text.startswith("/") or event.text in texts.MENU_BUTTONS):
                state = data.get("state")
                if state and (await state.get_state() or await state.get_data()):
                    await state.clear()
                    data["raw_state"] = None  # StateFilter shu qiymatga qaraydi (FSM middleware oldinroq hisoblagan)
            return await handler(event, data)

        # A'zo emas: faqat ro'yxatdan o'tish oqimiga ruxsat
        state = data.get("state")
        current = await state.get_state() if state else None
        if isinstance(event, Message):
            if (event.text or "").startswith("/start") or (current and current.startswith("Onboard")):
                return await handler(event, data)
            if event.chat.type == "private":
                await event.answer(texts.NOT_MEMBER)
            return None
        if isinstance(event, CallbackQuery):
            if (event.data or "").startswith(("role:", "nm:")) and current:
                return await handler(event, data)
            await event.answer("Bu bot faqat oila a'zolari uchun.", show_alert=True)
            return None
        return None


class RateLimiter:
    """AI so'rovlari uchun oddiy cheklov: bir kishi daqiqasiga N ta."""

    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self.hits: dict[int, deque] = defaultdict(deque)

    def allow(self, user_id: int) -> bool:
        now = time.monotonic()
        q = self.hits[user_id]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= self.per_minute:
            return False
        q.append(now)
        return True
