"""Ishga tushirish:  python -m hamyon"""
from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ErrorEvent, MenuButtonDefault

from hamyon.ai.client import AIClient
from hamyon.bot.handlers import commands, input as input_handlers, manage, start
from hamyon.bot.middlewares import AuthMiddleware
from hamyon.bot.scheduler import run_scheduler
from hamyon.config import settings
from hamyon.db.database import Database
from hamyon.services.engine import Engine

log = logging.getLogger("hamyon")


def setup_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    for noisy in ("aiogram.event", "httpx", "google_genai.models"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


async def main() -> None:
    setup_logging()
    if not settings.bot_token:
        sys.exit("❌ .env faylida BOT_TOKEN yo'q. @BotFather dan token olib qo'ying.")
    if not settings.gemini_api_key:
        sys.exit("❌ .env faylida GEMINI_API_KEY yo'q.")

    db = Database(settings.db_path)
    await db.connect()
    ai = AIClient(db)
    engine = Engine(db, ai)

    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML,
                                                                link_preview_is_disabled=True))
    dp = Dispatcher(storage=MemoryStorage())
    dp["db"] = db
    dp["engine"] = engine

    auth = AuthMiddleware()
    dp.message.outer_middleware(auth)
    dp.callback_query.outer_middleware(auth)
    # Tartib muhim: erkin matn handleri eng oxirida
    dp.include_routers(start.router, commands.router, manage.router, input_handlers.router)

    @dp.errors()
    async def on_error(event: ErrorEvent) -> bool:
        if isinstance(event.exception, TelegramBadRequest):
            msg = str(event.exception).lower()
            # Tugmani ikki marta bosish yoki eskirgan tugma - foydalanuvchini bezovta qilmaymiz
            if "message is not modified" in msg or "query is too old" in msg or "query id is invalid" in msg:
                log.info("E'tiborsiz qoldirildi: %s", event.exception)
                return True
        log.exception("Handler xatosi: %s", event.exception, exc_info=event.exception)
        update = event.update
        chat_id = None
        if update.message:
            chat_id = update.message.chat.id
        elif update.callback_query and update.callback_query.message:
            chat_id = update.callback_query.message.chat.id
        if chat_id:
            try:
                await bot.send_message(chat_id, "😔 Kutilmagan xato yuz berdi. Iltimos, qayta urinib ko'ring.")
            except Exception:
                pass
        return True

    # Hamma narsa tugmalar orqali: "/" buyruqlar menyusini o'chiramiz (eski /buyruqlar baribir ishlayveradi)
    await bot.delete_my_commands()
    await bot.set_chat_menu_button(menu_button=MenuButtonDefault())
    me = await bot.get_me()
    log.info("Bot ishga tushdi: @%s (model: %s)", me.username, ", ".join(ai.models))

    scheduler = asyncio.create_task(run_scheduler(bot, db, engine))
    try:
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.cancel()
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit) as exc:
        if isinstance(exc, SystemExit) and exc.code not in (None, 0):
            raise
