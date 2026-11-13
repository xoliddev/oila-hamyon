"""Matn yordamchilari (Telegram HTML)."""
from __future__ import annotations

import html
import re
import unicodedata
from decimal import Decimal

LINE = "─" * 18


def esc(value: object) -> str:
    return html.escape(str(value if value is not None else ""), quote=False)


def bar(pct: Decimal | float, width: int = 10) -> str:
    """Progress chizig'i: ▰▰▰▰▱▱▱▱▱▱"""
    p = max(Decimal(0), Decimal(str(pct)))
    filled = int(min(p, Decimal(100)) * width / 100 + Decimal("0.5"))
    return "▰" * filled + "▱" * (width - filled)


def chunk(text: str, limit: int = 3900) -> list[str]:
    """Uzun matnni Telegram limitiga mos bo'laklarga, qatorlar bo'yicha ajratadi."""
    if len(text) <= limit:
        return [text]
    parts, current = [], ""
    lines: list[str] = []
    for line in text.split("\n"):
        while len(line) > limit:  # bitta juda uzun qator ham bo'linadi
            lines.append(line[:limit])
            line = line[limit:]
        lines.append(line)
    for line in lines:
        if len(current) + len(line) + 1 > limit and current:
            parts.append(current)
            current = ""
        current += line + "\n"
    if current.strip():
        parts.append(current)
    return parts


_CYR = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo", "ж": "j", "з": "z",
    "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "у": "u", "ф": "f", "х": "x", "ц": "s", "ч": "ch", "ш": "sh", "щ": "sh",
    "ъ": "", "ы": "i", "ь": "", "э": "e", "ю": "yu", "я": "ya", "ў": "o'", "қ": "q", "ғ": "g'",
    "ҳ": "h",
}


def normalize_name(value: str | None) -> str:
    """Ismlarni solishtirish uchun: kichik harf, lotin, apostroflarsiz."""
    s = (value or "").strip().lower()
    s = "".join(_CYR.get(ch, ch) for ch in s)
    s = unicodedata.normalize("NFKD", s)
    s = re.sub(r"[ʻʼ'`‘’]", "", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()
