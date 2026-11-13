"""Fon vazifalari: kunlik xulosa, oylik hisobot, eslatmalar, kurslar, zaxira nusxa, tozalash.

Har 30 soniyada tekshiradi; har bir vazifa job_runs jadvali orqali kuniga/oyiga bir martagina bajariladi
(bot qayta ishga tushsa ham takrorlanmaydi).
"""
from __future__ import annotations

import asyncio
import logging
import tempfile
from datetime import date
from pathlib import Path

from aiogram import Bot
from aiogram.types import BufferedInputFile, FSInputFile

from hamyon.bot import keyboards as kb
from hamyon.bot.sender import broadcast
from hamyon.core import dates
from hamyon.core.money import fmt
from hamyon.core.text import esc
from hamyon.db.database import Database
from hamyon.services import charts, ledger, reports
from hamyon.services import family as fam
from hamyon.services.currency import get_rate
from hamyon.services.engine import Engine, _sanitize_html

log = logging.getLogger(__name__)
TICK = 30


async def _once(db: Database, job: str, key: str) -> bool:
    """True qaytarsa - vazifa hali bajarilmagan va hozir belgilandi."""
    exists = await db.fetchone("SELECT 1 FROM job_runs WHERE job=? AND key=?", (job, key))
    if exists:
        return False
    await db.execute("INSERT OR IGNORE INTO job_runs (job, key) VALUES (?,?)", (job, key))
    return True


async def run_scheduler(bot: Bot, db: Database, engine: Engine) -> None:
    log.info("Rejalashtiruvchi ishga tushdi")
    while True:
        try:
            await tick(bot, db, engine)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Rejalashtiruvchida xato")
        await asyncio.sleep(TICK)


async def tick(bot: Bot, db: Database, engine: Engine) -> None:
    now = dates.now()
    today = now.date()
    hm = now.strftime("%H:%M")
    for family in await fam.all_families(db):
        try:
            await family_jobs(bot, db, engine, family, today, hm)
        except Exception:
            log.exception("Oila #%s vazifalarida xato (boshqalari davom etadi)", family["id"])
    await global_jobs(bot, db, today, hm)


async def family_jobs(bot: Bot, db: Database, engine: Engine, family: dict, today: date, hm: str) -> None:
    fid = family["id"]
    # 1) kunlik xulosa
    if family["daily_report"] and hm >= family["daily_report_time"] and \
            await _once(db, "daily", f"{fid}:{today}"):
        text = await reports.daily_digest_text(db, fid, today)
        await broadcast(bot, db, fid, text)
    # 2) oylik hisobot - oyning 1-sanasi 09:00 dan (bot o'sha kuni o'chiq bo'lsa, 3-sanagacha yetkaziladi)
    if family["monthly_report"] and today.day <= 3 and hm >= "09:00":
        prev_start, prev_end = dates.period_bounds("prev_month", today)
        if await _once(db, "monthly", f"{fid}:{prev_start:%Y-%m}"):
            await send_monthly(bot, db, engine, fid, prev_start, prev_end)
    # 3) har oylik to'lov va qarz muddati eslatmalari
    if hm >= "09:00":
        await remind_recurring(bot, db, fid, today)
        await remind_debts(bot, db, fid, today)


async def global_jobs(bot: Bot, db: Database, today: date, hm: str) -> None:
    # 4) MB kurslarini oldindan olish (bir marta kuniga)
    if hm >= "10:00" and await _once(db, "fx", str(today)):
        for cur in ("USD", "EUR", "RUB"):
            try:
                await get_rate(db, cur, today)
            except Exception:
                log.warning("%s kursi olinmadi", cur)
    # 5) zaxira nusxa - har kuni 03:00 dan keyin adminlarga
    if hm >= "03:00" and await _once(db, "backup", str(today)):
        await send_backup(bot, db, today)
    # 6) tozalash
    if await _once(db, "cleanup", str(today)):
        await db.execute("DELETE FROM pending WHERE created_at < datetime('now', '-7 days')")
        await db.execute("DELETE FROM ai_log WHERE id < (SELECT IFNULL(MAX(id),0) - 3000 FROM ai_log)")
        await db.execute("DELETE FROM message_links WHERE created_at < datetime('now', '-180 days')")
        await db.execute("DELETE FROM job_runs WHERE ran_at < datetime('now', '-400 days')")


async def send_monthly(bot: Bot, db: Database, engine: Engine, fid: int, start: date, end: date) -> None:
    title = f"{dates.MONTHS_TITLE[start.month - 1]} oyi yakuni"
    text = await reports.period_report_text(db, fid, start, end, title)
    await broadcast(bot, db, fid, text)
    agg = await reports.aggregate(db, fid, start, end)
    if not agg.rows:
        return
    png = await charts.report_chart(agg, title)
    try:
        facts = await reports.insight_facts(db, fid, start, end)
        insight = _sanitize_html(await engine.ai.insight(facts))
    except Exception:
        log.exception("Oylik xulosa yozilmadi")
        insight = None
    for m in await fam.members(db, fid):
        try:
            await bot.send_photo(m["tg_id"], BufferedInputFile(png, "oy.png"), caption=f"📈 {title}")
            if insight:
                await bot.send_message(m["tg_id"], f"🧠 <b>Hisobchi xulosasi</b>\n\n{insight}")
        except Exception as exc:
            log.info("Oylik hisobot %s ga yetmadi: %s", m["name"], exc)


async def remind_recurring(bot: Bot, db: Database, fid: int, today: date) -> None:
    rows = await db.fetchall(
        """SELECT * FROM recurring WHERE family_id=? AND is_active=1 AND next_due<=?
           AND IFNULL(last_reminded,'')<>?""", (fid, today.isoformat(), today.isoformat()))
    for rec in rows:
        await db.execute("UPDATE recurring SET last_reminded=? WHERE id=?", (today.isoformat(), rec["id"]))
        due = date.fromisoformat(rec["next_due"])
        late = f"\n⚠️ Muddati {dates.fmt_date(due)} edi" if due < today else ""
        text = (f"🔔 <b>To'lov kuni</b>\n{esc(rec['description'])}: <b>{fmt(rec['amount'], rec['currency'])}</b>"
                f"{late}\n\nTo'lagan bo'lsangiz, tugmani bosing — o'zim yozib qo'yaman.")
        targets = [m for m in await fam.members(db, fid) if m["id"] == rec["member_id"]] or \
            await fam.members(db, fid)
        for m in targets:
            try:
                await bot.send_message(m["tg_id"], text, reply_markup=kb.recurring_due_kb(rec["id"]))
            except Exception:
                pass


async def remind_debts(bot: Bot, db: Database, fid: int, today: date) -> None:
    """Muddati kelgan qarzlar: muddat kuni va keyin har 7 kunda eslatadi."""
    for d in await ledger.open_debts(db, fid):
        if not d["due_on"]:
            continue
        due = date.fromisoformat(d["due_on"])
        last = date.fromisoformat(d["last_reminded"]) if d["last_reminded"] else None
        if due > today or (last and (today - last).days < 7):
            continue
        await db.execute("UPDATE debts SET last_reminded=? WHERE id=?", (today.isoformat(), d["id"]))
        if d["direction"] == "lent":
            text = (f"⏰ <b>{esc(d['counterparty'])}</b> qarzni qaytarish muddati keldi: "
                    f"<b>{fmt(d['remaining'], d['currency'])}</b> ({dates.fmt_date(due)})")
        else:
            text = (f"⏰ <b>{esc(d['counterparty'])}</b>ga qarzimizni qaytarish muddati: "
                    f"<b>{fmt(d['remaining'], d['currency'])}</b> ({dates.fmt_date(due)})")
        await broadcast(bot, db, fid, text + "\n\nBatafsil: 🤝 Qarzlar tugmasi")


async def send_backup(bot: Bot, db: Database, today: date) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"hamyon_{today.isoformat()}.db"
        await db.backup_to(path)
        for family in await fam.all_families(db):
            for m in await fam.members(db, family["id"]):
                if not m["is_admin"]:
                    continue
                try:
                    await bot.send_document(
                        m["tg_id"], FSInputFile(path), disable_notification=True,
                        caption="💾 Kunlik zaxira nusxa. Server buzilsa ham ma'lumot yo'qolmaydi — shu faylni "
                                "data/hamyon.db sifatida qo'yish kifoya.")
                except Exception as exc:
                    log.info("Zaxira yuborilmadi: %s", exc)
