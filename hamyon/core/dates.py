"""Sana va davrlar (Toshkent vaqti bo'yicha)."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from hamyon.config import settings

MONTHS = ["yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul",
          "avgust", "sentabr", "oktabr", "noyabr", "dekabr"]
MONTHS_TITLE = [m.capitalize() for m in MONTHS]
WEEKDAYS = ["dushanba", "seshanba", "chorshanba", "payshanba", "juma", "shanba", "yakshanba"]
WEEKDAYS_SHORT = ["Du", "Se", "Ch", "Pa", "Ju", "Sh", "Ya"]


def now() -> datetime:
    return datetime.now(settings.tz)


def today() -> date:
    return now().date()


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return None


def month_start(d: date) -> date:
    return d.replace(day=1)


def month_end(d: date) -> date:
    nxt = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return nxt - timedelta(days=1)


def add_months(d: date, n: int, day: int | None = None) -> date:
    m = d.month - 1 + n
    y = d.year + m // 12
    m = m % 12 + 1
    target_day = day or d.day
    last = month_end(date(y, m, 1)).day
    return date(y, m, min(target_day, last))


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


PERIODS = {
    "today": "Bugun",
    "yesterday": "Kecha",
    "week": "Shu hafta",
    "last7": "So'nggi 7 kun",
    "month": "Shu oy",
    "prev_month": "O'tgan oy",
    "last30": "So'nggi 30 kun",
    "year": "Shu yil",
}


def period_bounds(key: str, ref: date | None = None) -> tuple[date, date]:
    t = ref or today()
    if key == "today":
        return t, t
    if key == "yesterday":
        y = t - timedelta(days=1)
        return y, y
    if key == "week":
        return week_start(t), t
    if key == "last7":
        return t - timedelta(days=6), t
    if key == "month":
        return month_start(t), t
    if key == "prev_month":
        end = month_start(t) - timedelta(days=1)
        return month_start(end), end
    if key == "last30":
        return t - timedelta(days=29), t
    if key == "year":
        return date(t.year, 1, 1), t
    raise ValueError(key)


def fmt_date(d: date, with_year: bool | None = None) -> str:
    if with_year is None:
        with_year = d.year != today().year
    text = f"{d.day}-{MONTHS[d.month - 1]}"
    return f"{text}, {d.year}" if with_year else text


def fmt_short(d: date) -> str:
    return f"{d.day:02d}.{d.month:02d}"


def fmt_range(start: date, end: date) -> str:
    if start == end:
        return fmt_date(start)
    if start.day == 1 and end == month_end(start):
        return f"{MONTHS_TITLE[start.month - 1]} {start.year}"
    if start.year == end.year and start.month == end.month:
        return f"{start.day}–{end.day}-{MONTHS[start.month - 1]}"
    return f"{fmt_date(start)} – {fmt_date(end)}"


def relative_label(d: date, ref: date | None = None) -> str:
    t = ref or today()
    delta = (t - d).days
    if delta == 0:
        return "bugun"
    if delta == 1:
        return "kecha"
    if delta == 2:
        return "o'tgan kun (2 kun oldin)"
    return f"{delta} kun oldin" if delta > 0 else f"{-delta} kundan keyin"


def recent_days_table(ref: date | None = None, days: int = 10) -> str:
    """AI uchun: 'kecha', 'seshanba kuni' kabi so'zlarni xatosiz sanaga aylantirish jadvali."""
    t = ref or today()
    lines = []
    for i in range(days):
        d = t - timedelta(days=i)
        lines.append(f"  {d.isoformat()} — {WEEKDAYS[d.weekday()]} ({relative_label(d, t)})")
    return "\n".join(lines)
