"""Buyruqlar va menyu tugmalari: hisobot, balans, tarix, qarzlar, limitlar, eslatmalar, oila."""
from __future__ import annotations

import asyncio
from datetime import date

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from aiogram.utils.chat_action import ChatActionSender
from aiogram.utils.keyboard import InlineKeyboardBuilder

from hamyon.bot import keyboards as kb
from hamyon.bot import texts
from hamyon.bot.sender import deliver, send_text
from hamyon.core import dates
from hamyon.core.money import fmt, fmt_decimal
from hamyon.core.text import LINE, esc
from hamyon.db.database import Database
from hamyon.services import budgets as budgets_svc
from hamyon.services import charts, export, ledger, reports
from hamyon.services import family as fam
from hamyon.services.ai_actions import make_action
from hamyon.services.engine import Engine
from hamyon.services.ledger import KIND_EMOJI, KIND_LABEL

router = Router(name="commands")


# ------------------------------------------------------------------ yordam
@router.message(Command("yordam", "help"))
@router.message(F.text == texts.BTN_HELP)
async def cmd_help(message: Message) -> None:
    await message.answer(texts.HELP, reply_markup=kb.main_menu())


# ------------------------------------------------------------------ hisobot
@router.message(Command("hisobot"))
@router.message(F.text == texts.BTN_REPORT)
async def cmd_report(message: Message) -> None:
    await message.answer("📊 Qaysi davr uchun hisobot?", reply_markup=kb.periods_kb())


@router.callback_query(kb.RepCb.filter())
async def report_cb(call: CallbackQuery, callback_data: kb.RepCb, db: Database, member: dict, bot: Bot,
                    engine: Engine) -> None:
    period = callback_data.period
    if period not in dates.PERIODS:
        await call.answer("Noma'lum davr")
        return
    start, end = dates.period_bounds(period)
    family_id = member["family_id"]
    title = dates.PERIODS[period]
    if callback_data.action == "menu":
        await call.answer()
        await call.message.answer("📊 Qaysi davr uchun hisobot?", reply_markup=kb.periods_kb())
        return
    if callback_data.action == "show":
        await call.answer()
        text = await reports.period_report_text(db, family_id, start, end, title)
        await send_text(bot, call.message.chat.id, text, kb.report_actions_kb(period))
        return
    if callback_data.action == "chart":
        await call.answer("Chizyapman...")
        async with ChatActionSender.upload_photo(bot=bot, chat_id=call.message.chat.id):
            agg = await reports.aggregate(db, family_id, start, end)
            png = await charts.report_chart(agg, f"{title}: {dates.fmt_range(start, end)}")
        await call.message.answer_photo(BufferedInputFile(png, "hisobot.png"),
                                        caption=f"📈 {title} · {dates.fmt_range(start, end)}")
        return
    if callback_data.action == "xlsx":
        await call.answer("Tayyorlayapman...")
        async with ChatActionSender.upload_document(bot=bot, chat_id=call.message.chat.id):
            data = await export.build_xlsx(db, family_id, start, end)
        name = f"hamyon_{start.isoformat()}_{end.isoformat()}.xlsx"
        await call.message.answer_document(BufferedInputFile(data, name),
                                           caption=f"📥 {title} · {dates.fmt_range(start, end)}")
        return
    if callback_data.action == "insight":
        await call.answer("O'ylayapman... 🧠")
        async with ChatActionSender.typing(bot=bot, chat_id=call.message.chat.id):
            facts = await reports.insight_facts(db, family_id, start, end)
            try:
                text = await engine.ai.insight(facts)
            except Exception:
                text = "😔 Hozir tahlil qila olmadim, birozdan so'ng urinib ko'ring."
        from hamyon.services.engine import _sanitize_html
        await send_text(bot, call.message.chat.id,
                        f"🧠 <b>Hisobchi xulosasi</b> · {dates.fmt_range(start, end)}\n\n{_sanitize_html(text)}")


# ------------------------------------------------------------------ balans
@router.message(Command("balans"))
@router.message(F.text == texts.BTN_BALANCE)
async def cmd_balance(message: Message, db: Database, member: dict) -> None:
    text, _ = await reports.wallets_text(db, member["family_id"])
    debts = await ledger.open_debts(db, member["family_id"])
    lent = sum(d["remaining"] for d in debts if d["direction"] == "lent" and d["currency"] == "UZS")
    borrowed = sum(d["remaining"] for d in debts if d["direction"] == "borrowed" and d["currency"] == "UZS")
    if lent or borrowed:
        text += "\n"
        if lent:
            text += f"\n📤 Bizga qarzdorlar: {fmt(lent)}"
        if borrowed:
            text += f"\n📥 Bizning qarzimiz: {fmt(borrowed)}"
    text += ("\n\n<i>Qoldiq haqiqatga mos kelmasa, shunchaki yozing: «kartamda 1 230 000 bor» — "
             "farqni topib, to'g'rilab qo'yaman.</i>")
    await message.answer(text)


# ------------------------------------------------------------------ tarix
def _tx_line(n: int, t: dict) -> str:
    d = date.fromisoformat(t["occurred_on"])
    emoji = t["category_emoji"] or KIND_EMOJI.get(t["kind"], "•")
    sign = "+" if t["kind"] in ("income", "debt_take", "debt_repay_in") else ""
    if t["kind"] == "adjustment":
        sign = "+" if (t["wallet_amount"] or 0) > 0 else "−"
    who = f" · {esc(t['member_name'])}" if t["member_name"] else ""
    return (f"<b>{n}.</b> {dates.fmt_short(d)} {emoji} {esc(t['description'])} — "
            f"<b>{sign}{fmt(t['amount'], t['currency'])}</b>{who}")


async def _history(db: Database, family_id: int, offset: int) -> tuple[str, object]:
    rows = await ledger.recent_transactions(db, family_id, limit=16, offset=offset)
    has_more = len(rows) > 15
    rows = rows[:15]
    if not rows:
        return "📒 Hali hech narsa yozilmagan.", None
    lines = ["📒 <b>Oxirgi yozuvlar</b>", "<i>Ko'rish, tuzatish yoki o'chirish uchun pastdagi raqamni bosing</i>", ""]
    lines += [_tx_line(offset + i, t) for i, t in enumerate(rows, 1)]
    return "\n".join(lines), kb.history_kb([t["id"] for t in rows], offset, has_more)


@router.message(Command("tarix"))
@router.message(F.text == texts.BTN_HISTORY)
async def cmd_history(message: Message, db: Database, member: dict) -> None:
    text, markup = await _history(db, member["family_id"], 0)
    await message.answer(text, reply_markup=markup)


@router.callback_query(kb.HistCb.filter())
async def history_page(call: CallbackQuery, callback_data: kb.HistCb, db: Database, member: dict) -> None:
    text, markup = await _history(db, member["family_id"], callback_data.offset)
    await call.answer()
    await call.message.edit_text(text, reply_markup=markup)


@router.callback_query(kb.TxCb.filter(F.action == "view"))
async def tx_view(call: CallbackQuery, callback_data: kb.TxCb, db: Database, member: dict) -> None:
    await call.answer()
    await _tx_detail(call.message, db, member, callback_data.tx_id)


@router.message(F.text.regexp(r"^/t(\d+)(@\w+)?$").as_("match"))
async def tx_detail(message: Message, match, db: Database, member: dict) -> None:
    await _tx_detail(message, db, member, int(match.group(1)))


async def _tx_detail(message: Message, db: Database, member: dict, tx_id: int) -> None:
    rows = await ledger.transactions_by_ids(db, member["family_id"], [tx_id])
    if not rows:
        await message.answer("Bu yozuv topilmadi yoki o'chirilgan.")
        return
    t = rows[0]
    lines = [f"🧾 <b>Yozuv #{t['id']}</b>", "",
             f"Turi: {KIND_LABEL.get(t['kind'], t['kind'])}",
             f"Izoh: <b>{esc(t['description'])}</b>",
             f"Summa: <b>{fmt(t['amount'], t['currency'])}</b>"]
    if t["currency"] != "UZS":
        lines.append(f"So'mda: {fmt(t['amount_base'])} (kurs {fmt_decimal(t['rate'])})")
    if t["quantity"]:
        lines.append(f"Miqdor: {fmt_decimal(t['quantity'])} {esc(t['unit'] or '')}")
    if t["category_name"]:
        lines.append(f"Kategoriya: {t['category_emoji']} {esc(t['category_name'])}")
    lines.append(f"Sana: {dates.fmt_date(date.fromisoformat(t['occurred_on']), True)}")
    if t["wallet_name"]:
        lines.append(f"Hamyon: {esc(t['wallet_name'])}" + (f" → {esc(t['to_wallet_name'])}" if t["to_wallet_name"] else ""))
    if t["on_credit"]:
        lines.append(f"Nasiya: {esc(t['counterparty'])}")
    elif t["counterparty"]:
        lines.append(f"Qarshi tomon: {esc(t['counterparty'])}")
    lines.append(f"Kimniki: {esc(t['member_name'] or '—')} · yozgan: {esc(t['created_by_name'] or '—')}")
    sent = await message.answer("\n".join(lines), reply_markup=kb.tx_kb(t["id"]))
    await ledger.link_message(db, sent.chat.id, sent.message_id, t["batch_id"], [t["id"]])


# ------------------------------------------------------------------ bekor
@router.message(Command("bekor"))
@router.message(F.text == texts.BTN_UNDO)
async def cmd_undo(message: Message, engine: Engine, member: dict) -> None:
    reply = await engine.undo_last(member)
    markup = kb.redo_kb(reply.batch_id) if reply.batch_id else None
    await message.answer(reply.text, reply_markup=markup)


# ------------------------------------------------------------------ qarzlar
@router.message(Command("qarzlar"))
@router.message(F.text == texts.BTN_DEBTS)
async def cmd_debts(message: Message, db: Database, member: dict) -> None:
    debts = await ledger.open_debts(db, member["family_id"])
    if not debts:
        await message.answer("🤝 Ochiq qarzlar yo'q. Zo'r! 🎉\n\n"
                             "<i>Yozish: «Akmalga 300 ming qarz berdim» yoki «qo'shnidan 1 mln qarz oldim»</i>")
        return
    lent = [d for d in debts if d["direction"] == "lent"]
    borrowed = [d for d in debts if d["direction"] == "borrowed"]
    lines = ["🤝 <b>Qarzlar</b>"]
    b = InlineKeyboardBuilder()
    today = dates.today()
    for title, group in (("📤 Bizga qarzdorlar", lent), ("📥 Biz qarzdormiz", borrowed)):
        if not group:
            continue
        lines += ["", f"<b>{title}:</b>"]
        for d in group:
            line = f"• {esc(d['counterparty'])} — <b>{fmt(d['remaining'], d['currency'])}</b>"
            if d["remaining"] != d["amount"]:
                line += f" <i>(dastlab {fmt(d['amount'], d['currency'])})</i>"
            if d["due_on"]:
                due = date.fromisoformat(d["due_on"])
                line += f"\n   muddat: {dates.fmt_date(due)}" + (" ⏰ <b>o'tib ketdi</b>" if due < today else "")
            line += f"\n   <i>{dates.fmt_date(date.fromisoformat(d['opened_on']))} dan beri</i>"
            lines.append(line)
            label = "qaytardi" if d["direction"] == "lent" else "to'landi"
            b.button(text=f"✅ {d['counterparty'][:18]} — to'liq {label}",
                     callback_data=kb.DebtCb(action="close", debt_id=d["id"]))
    b.adjust(1)
    lines += ["", "<i>Qisman qaytarilsa yozing: «Akmal 100 ming qaytardi»</i>"]
    await message.answer("\n".join(lines), reply_markup=b.as_markup())


@router.callback_query(kb.DebtCb.filter(F.action == "close"))
async def debt_close(call: CallbackQuery, callback_data: kb.DebtCb, db: Database, member: dict, engine: Engine,
                     bot: Bot) -> None:
    # Qulf ichida qayta tekshiramiz: ikki marta bosish yoki ikki kishi bir vaqtda bossa ham faqat bir marta yoziladi
    async with _debt_close_lock:
        debt = await ledger.get_debt(db, member["family_id"], callback_data.debt_id)
        if not debt or debt["remaining"] <= 0:
            await call.answer("Bu qarz allaqachon yopilgan.", show_alert=True)
            return
        kind = "debt_repay_in" if debt["direction"] == "lent" else "debt_repay_out"
        action = make_action(type=kind, counterparty=debt["counterparty"], currency=debt["currency"],
                             amount_expr=_major(debt["remaining"]),
                             description=f"{debt['counterparty']}: qarz yopildi")
        ops, problems = await engine.prepare_ops(member, [action])
        if not ops:
            await call.answer()
            await call.message.answer("🤔 Yozib bo'lmadi: " + "; ".join(problems))
            return
        ops[0].debt_id = debt["id"]
        ops[0].warnings = [w for w in ops[0].warnings if "ochiq qarz topilmadi" not in w]
        reply = await engine.commit(member, ops, problems, source="manual", raw_text="qarz yopildi tugmasi",
                                    transcript=None, store=None)
    await call.answer("Yopildi ✅")
    await deliver(bot, db, member, call.message.chat.id, [reply])


_debt_close_lock = asyncio.Lock()


def _major(minor: int) -> str:
    from hamyon.core.money import from_minor
    return format(from_minor(minor), "f")


# ------------------------------------------------------------------ limitlar
@router.message(Command("byudjet", "limit"))
@router.message(F.text == texts.BTN_BUDGET)
async def cmd_budget(message: Message, db: Database, member: dict) -> None:
    rows = await budgets_svc.budget_status(db, member["family_id"])
    if not rows:
        await message.answer("🎯 <b>Oylik limitlar</b>\n\nHali limit qo'yilmagan.\n\n"
                             "Yozing, masalan:\n<i>oziq-ovqatga oyiga 3 mln limit qo'y</i>\n"
                             "<i>umumiy oylik limit 9 mln</i>\n\n"
                             "80% va 100% ga yetganda ogohlantiraman.")
        return
    today = dates.today()
    lines = [f"🎯 <b>Oylik limitlar</b> · {dates.MONTHS_TITLE[today.month - 1]}", ""]
    b = InlineKeyboardBuilder()
    for r in rows:
        lines += [budgets_svc.render_budget_line(r), ""]
        b.button(text=f"🗑 {(r['category_name'] or 'Umumiy')[:20]}", callback_data=kb.BudCb(action="del", bid=r["id"]))
    b.adjust(2)
    lines.append("<i>O'zgartirish: «kafega oyiga 600 ming limit» · O'chirish: pastdagi tugmalar</i>")
    await message.answer("\n".join(lines), reply_markup=b.as_markup())


@router.callback_query(kb.BudCb.filter(F.action == "del"))
async def budget_delete(call: CallbackQuery, callback_data: kb.BudCb, db: Database, member: dict) -> None:
    await budgets_svc.delete_budget(db, member["family_id"], callback_data.bid)
    await call.answer("Limit o'chirildi")
    await call.message.edit_reply_markup()
    await call.message.answer("🗑 Limit olib tashlandi. Yangi holat: 🎯 Limitlar tugmasida.")


# ------------------------------------------------------------------ takroriy to'lovlar
@router.message(Command("rejali"))
@router.message(F.text == texts.BTN_RECURRING)
async def cmd_recurring(message: Message, db: Database, member: dict) -> None:
    rows = await budgets_svc.list_recurring(db, member["family_id"])
    if not rows:
        await message.answer("🔔 <b>Har oylik to'lovlar</b>\n\nHali yo'q. Yozing, masalan:\n"
                             "<i>har oy 5-sanada internetga 120 ming to'laymiz</i>\n"
                             "<i>har oyning 10-sida kvartplata 350 ming</i>\n\n"
                             "O'sha kuni eslataman, «To'landi» bossangiz o'zim yozib qo'yaman.")
        return
    lines = ["🔔 <b>Har oylik to'lovlar</b>", ""]
    b = InlineKeyboardBuilder()
    total = 0
    for r in rows:
        lines.append(f"{r['emoji'] or '•'} {esc(r['description'])} — <b>{fmt(r['amount'], r['currency'])}</b>\n"
                     f"   har oy {r['day_of_month']}-sana · keyingisi {dates.fmt_date(date.fromisoformat(r['next_due']))}")
        if r["currency"] == "UZS" and r["kind"] == "expense":
            total += r["amount"]
        b.button(text=f"🗑 {r['description'][:22]}", callback_data=kb.RecurCb(action="del", rid=r["id"]))
    b.adjust(2)
    lines += [LINE, f"Oyiga majburiy to'lovlar: <b>{fmt(total)}</b>"]
    await message.answer("\n".join(lines), reply_markup=b.as_markup())


@router.callback_query(kb.RecurCb.filter())
async def recurring_cb(call: CallbackQuery, callback_data: kb.RecurCb, db: Database, member: dict, engine: Engine,
                       bot: Bot) -> None:
    rec = await budgets_svc.get_recurring(db, member["family_id"], callback_data.rid)
    if not rec or not rec["is_active"]:
        await call.answer("Bu eslatma topilmadi.", show_alert=True)
        return
    if callback_data.action == "del":
        await budgets_svc.deactivate_recurring(db, member["family_id"], rec["id"])
        await call.answer("O'chirildi")
        await call.message.answer(f"🗑 «{esc(rec['description'])}» eslatmasi o'chirildi.")
        return
    await call.message.edit_reply_markup()
    # Atomar egallash: muddat hali kelgan bo'lsa, keyingi oyga suramiz. Eski eslatma tugmasi yoki ikkinchi bosish
    # hech narsa qilmaydi (pul ikki marta yozilmaydi, oy o'tkazib yuborilmaydi).
    if not await budgets_svc.claim_recurring(db, rec, dates.today()):
        await call.answer("Bu oy uchun allaqachon belgilangan ✅", show_alert=True)
        return
    if callback_data.action == "skip":
        await call.answer("Bu oy o'tkazib yuborildi")
        return
    # paid
    await call.answer()
    cat =await db.fetchone("SELECT key FROM categories WHERE id=?", (rec["category_id"],)) if rec["category_id"] else None
    wallet = await fam.get_wallet(db, rec["wallet_id"]) if rec["wallet_id"] else None
    action = make_action(type=rec["kind"], description=rec["description"], amount_expr=_major(rec["amount"]),
                         currency=rec["currency"], category=cat["key"] if cat else None,
                         wallet=wallet["name"] if wallet else None)
    try:
        ops, problems = await engine.prepare_ops(member, [action])
        if not ops:
            raise ValueError("; ".join(problems))
        reply = await engine.commit(member, ops, problems, source="recurring", raw_text=rec["description"],
                                    transcript=None, store=None)
    except Exception as exc:
        await budgets_svc.unclaim_recurring(db, rec)  # muvaffaqiyatsiz - muddatni qaytaramiz
        await call.message.answer(f"🤔 Yozib bo'lmadi: {esc(exc)}")
        return
    await deliver(bot, db, member, call.message.chat.id, [reply])


# ------------------------------------------------------------------ oila
@router.message(Command("oila"))
async def cmd_family(message: Message, db: Database, member: dict) -> None:
    family_id = member["family_id"]
    s, e = dates.period_bounds("month")
    agg = await reports.aggregate(db, family_id, s, e)
    lines = ["👨‍👩‍👦 <b>Oila a'zolari</b>", ""]
    b = InlineKeyboardBuilder()
    for m in await fam.members(db, family_id):
        crown = " 👑" if m["is_admin"] else ""
        spent = agg.by_member.get(m["name"], 0)
        lines.append(f"• <b>{esc(m['name'])}</b> — {esc(m['role'])}{crown}\n   shu oy sarfladi: {fmt(spent)}")
        if member["is_admin"] and m["id"] != member["id"]:
            b.button(text=f"🚫 {m['name'][:20]} ni chiqarish", callback_data=kb.MemCb(action="off", mid=m["id"]))
    if member["is_admin"]:
        b.button(text="🔗 Taklif havolasi", callback_data=kb.MemCb(action="invite", mid=0))
    b.adjust(1)
    await message.answer("\n".join(lines), reply_markup=b.as_markup())


async def _invite_text(db: Database, bot: Bot, family_id: int) -> str:
    family = await fam.get_family(db, family_id)
    me = await bot.get_me()
    return (f"🔗 <b>Taklif havolasi</b>\n\nhttps://t.me/{me.username}?start={family['invite_code']}\n\n"
            "Shu havolani bosgan odam oilangizga qo'shiladi. Havola begona qo'liga tushsa — "
            "«🔄 Yangilash» ni bosing, eskisi ishlamay qoladi.")


@router.message(Command("taklif"))
async def cmd_invite(message: Message, db: Database, member: dict, bot: Bot) -> None:
    if not member["is_admin"]:
        await message.answer("Taklif havolasini faqat oila boshlig'i (👑) bera oladi.")
        return
    b = InlineKeyboardBuilder()
    b.button(text="🔄 Yangilash", callback_data=kb.MemCb(action="newlink", mid=0))
    await message.answer(await _invite_text(db, bot, member["family_id"]), reply_markup=b.as_markup())


@router.callback_query(kb.MemCb.filter())
async def member_cb(call: CallbackQuery, callback_data: kb.MemCb, db: Database, member: dict, bot: Bot) -> None:
    if not member["is_admin"]:
        await call.answer("Faqat oila boshlig'i uchun.", show_alert=True)
        return
    if callback_data.action == "invite":
        await call.answer()
        await cmd_invite(call.message, db, member, bot)
        return
    if callback_data.action == "newlink":
        await fam.regenerate_invite(db, member["family_id"])
        await call.answer("Yangi havola tayyor")
        await call.message.edit_text(await _invite_text(db, bot, member["family_id"]))
        return
    if callback_data.action == "off":
        target = await fam.get_member(db, callback_data.mid)
        if not target or target["family_id"] != member["family_id"] or target["id"] == member["id"]:
            await call.answer("Mumkin emas", show_alert=True)
            return
        await fam.set_member_active(db, target["id"], False)
        await call.answer("Chiqarildi")
        await call.message.answer(f"🚫 {esc(target['name'])} oiladan chiqarildi. Uning yozuvlari saqlanib qoladi.")
