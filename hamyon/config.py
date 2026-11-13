"""Sozlamalar .env faylidan o'qiladi."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _int_or_none(value: str | None) -> int | None:
    value = (value or "").strip()
    return int(value) if value.lstrip("-").isdigit() else None


@dataclass(frozen=True)
class Settings:
    bot_token: str
    gemini_api_key: str
    gemini_model: str
    gemini_fallback_model: str
    db_path: Path
    tz: ZoneInfo
    owner_tg_id: int | None
    ai_rate_per_minute: int
    log_level: str


def load_settings() -> Settings:
    db_path = Path(os.getenv("DB_PATH", "data/hamyon.db"))
    if not db_path.is_absolute():
        db_path = ROOT / db_path
    return Settings(
        bot_token=os.getenv("BOT_TOKEN", "").strip(),
        gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash").strip(),
        gemini_fallback_model=os.getenv("GEMINI_FALLBACK_MODEL", "gemini-2.5-flash,gemini-flash-lite-latest").strip(),
        db_path=db_path,
        tz=ZoneInfo(os.getenv("TIMEZONE", "Asia/Tashkent").strip() or "Asia/Tashkent"),
        owner_tg_id=_int_or_none(os.getenv("OWNER_TG_ID")),
        ai_rate_per_minute=_int_or_none(os.getenv("AI_RATE_PER_MINUTE")) or 12,
        log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper(),
    )


settings = load_settings()
