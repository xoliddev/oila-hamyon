"""Valyuta kurslari - O'zbekiston Markaziy banki (cbu.uz) rasmiy kursi, bazada keshlanadi."""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal, InvalidOperation

import aiohttp

from hamyon.db.database import Database

log = logging.getLogger(__name__)
CBU_URL = "https://cbu.uz/uz/arkhiv-kursov-valyut/json/{ccy}/{day}/"
BASE = "UZS"


class RateUnavailable(RuntimeError):
    pass


async def _fetch_cbu(currency: str, day: date) -> tuple[Decimal, date] | None:
    url = CBU_URL.format(ccy=currency, day=day.isoformat())
    try:
        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json(content_type=None)
    except Exception as exc:  # tarmoq yo'q bo'lsa ham bot ishlashda davom etadi
        log.warning("CBU kursini olib bo'lmadi (%s %s): %s", currency, day, exc)
        return None
    if not data:
        return None
    item = data[0]
    try:
        rate = Decimal(str(item["Rate"]).replace(",", "."))
        nominal = Decimal(str(item.get("Nominal", "1")) or "1")
        d, m, y = str(item["Date"]).split(".")
        return rate / nominal, date(int(y), int(m), int(d))
    except (KeyError, ValueError, InvalidOperation):
        return None


async def get_rate(db: Database, currency: str, day: date) -> Decimal:
    """1 birlik `currency` necha so'm ekanini qaytaradi (o'sha sanadagi rasmiy kurs)."""
    currency = (currency or BASE).upper()
    if currency == BASE:
        return Decimal(1)
    row = await db.fetchone("SELECT rate FROM fx_rates WHERE currency=? AND date=?", (currency, day.isoformat()))
    if row:
        return Decimal(row["rate"])
    fetched = await _fetch_cbu(currency, day)
    if fetched:
        rate, _ = fetched
        await db.execute(
            "INSERT OR REPLACE INTO fx_rates (currency, date, rate) VALUES (?,?,?)",
            (currency, day.isoformat(), str(rate)),
        )
        return rate
    row = await db.fetchone(
        "SELECT rate FROM fx_rates WHERE currency=? AND date<=? ORDER BY date DESC LIMIT 1",
        (currency, day.isoformat()),
    ) or await db.fetchone(
        "SELECT rate FROM fx_rates WHERE currency=? ORDER BY date DESC LIMIT 1", (currency,)
    )
    if row:
        return Decimal(row["rate"])
    raise RateUnavailable(f"{currency} kursini aniqlab bo'lmadi")


async def set_manual_rate(db: Database, currency: str, day: date, rate: Decimal) -> None:
    await db.execute(
        "INSERT OR REPLACE INTO fx_rates (currency, date, rate) VALUES (?,?,?)",
        (currency.upper(), day.isoformat(), str(rate)),
    )
