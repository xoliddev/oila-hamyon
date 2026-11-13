"""Asosiy dvigatel: xabar -> AI -> tekshiruv -> aniq hisob -> saqlash -> javob.

Telegramga bog'liq emas: shu sababli uni konsol simulyatori va testlardan ham ishlatish mumkin.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from hamyon.ai.client import AIClient, AIError
from hamyon.ai.context import build_context
from hamyon.ai.schemas import Action, ParseResult
from hamyon.core import dates
from hamyon.core.money import (AmountError, convert_minor, eval_amount, fmt, fmt_decimal, fmt_percent,
                               from_minor, parse_minor, percent, split_proportionally, to_minor)
from hamyon.core.text import LINE, esc, normalize_name
from hamyon.db.database import Database
from hamyon.services import budgets as budgets_svc
from hamyon.services import family as fam
from hamyon.services import ledger, queries, reports
from hamyon.services.currency import RateUnavailable, get_rate
from hamyon.services.ledger import KIND_EMOJI, Op

log = logging.getLogger(__name__)

RECORD_TYPES = {"expense", "income", "transfer", "debt_give", "debt_take", "debt_repay_in", "debt_repay_out",
                "balance_set"}

AI_DOWN_TEXT = ("😔 Hozir sun'iy intellekt javob bermayapti (limit yoki tarmoq). Bir daqiqadan so'ng qayta "
                "urinib ko'ring — yozganingiz yo'qolmaydi, shunchaki qayta yuboring.")


@dataclass
class Reply:
    text: str
    kind: str = "info"              # saved | confirm | info | question | error
    batch_id: int | None = None
    tx_ids: list[int] = field(default_factory=list)
    pending_id: int | None = None
    notify_text: str | None = None  # boshqa oila a'zolariga
    show_undo: bool = False


class Engine:
    def __init__(self, db: Database, ai: AIClient):
        self.db = db
        self.ai = ai

    # ================================================================ kirish nuqtasi
    async def handle(self, member: dict, *, text: str | None = None, audio: bytes | None = None,
                     audio_mime: str = "audio/ogg", image: bytes | None = None,
                     image_mime: str = "image/jpeg") -> list[Reply]:
        source = "voice" if audio is not None else "photo" if image is not None else "text"
        context = await build_context(self.db, member)
        try:
            result = await self.ai.parse(context, text, audio=audio, audio_mime=audio_mime, image=image,
                                         image_mime=image_mime, member_id=member["id"])
        except AIError:
            log.exception("AI parse xatosi")
            return [Reply(AI_DOWN_TEXT, kind="error")]
        return await self.process_result(member, result, source=source, raw_text=text)

    async def process_result(self, member: dict, result: ParseResult, *, source: str,
                             raw_text: str | None) -> list[Reply]:
        replies: list[Reply] = []
        prefix = ""
        if result.transcript and source == "voice":
            prefix = f"🎙 <i>«{esc(result.transcript)}»</i>\n\n"

        record = [a for a in result.actions if a.type in RECORD_TYPES]
        configs = [a for a in result.actions if a.type in ("budget_set", "recurring_add")]
        asks = [a for a in result.actions if a.type == "query"]
        undo = any(a.type == "undo" for a in result.actions)
        chat = [a for a in result.actions if a.type == "chat"]

        if undo:
            replies.append(await self.undo_last(member))

        if record:
            ops, problems = await self.prepare_ops(member, record)
            if source == "photo":
                problems += self._reconcile_receipt(ops, result)
            if ops:
                replies.append(await self._save_or_confirm(member, ops, problems, source=source,
                                                           raw_text=raw_text, transcript=result.transcript,
                                                           store=result.receipt_store))
            elif problems:
                replies.append(Reply("🤔 " + "\n".join(problems) + "\n\nIltimos, aniqroq qilib qayta yozing.",
                                     kind="question"))

        for a in configs:
            replies.append(await self._apply_config(member, a))

        for a in asks:
            replies.append(await self.answer_query(member, a, raw_text or result.transcript or ""))

        if result.needs_clarification and result.clarification_question:
            replies.append(Reply("🤔 " + esc(result.clarification_question), kind="question"))

        if chat and not replies:
            reply_text = result.reply_text or next((a.note for a in chat if a.note), None)
            replies.append(Reply(esc(reply_text or "Men shu yerdaman 🙂 Harajatni oddiy yozib yuboring."),
                                 kind="info"))
        if not replies:
            replies.append(Reply(esc(result.reply_text) if result.reply_text else
                                 "🤔 Tushunmadim. Masalan shunday yozing: <i>non 6 ming, sut 12 ming</i>",
                                 kind="question"))
        if prefix:
            replies[0].text = prefix + replies[0].text
        return replies

    # ================================================================ tayyorlash (validatsiya)
    async def prepare_ops(self, member: dict, actions: list[Action]) -> tuple[list[Op], list[str]]:
        family_id = member["family_id"]
        members = await fam.members(self.db, family_id)
        wallets = await fam.wallets(self.db, family_id)
        cats = {c["key"]: c for c in await fam.categories(self.db, family_id)}
        debts = await ledger.open_debts(self.db, family_id)
        default_wallet = await fam.default_wallet(self.db, family_id, member)
        ops: list[Op] = []
        problems: list[str] = []
        for a in actions:
            try:
                ops.append(await self._prepare_one(member, a, members, wallets, cats, debts, default_wallet))
            except (AmountError, ValueError, RateUnavailable) as exc:
                what = a.description or "yozuv"
                problems.append(f"«{esc(what)}»: {esc(exc)}")
        return ops, problems

    async def _prepare_one(self, member: dict, a: Action, members: list[dict], wallets: list[dict],
                           cats: dict, debts: list[dict], default_wallet: dict | None) -> Op:
        today = dates.today()
        kind = "adjustment" if a.type == "balance_set" else a.type
        amount_dec = eval_amount(a.amount_expr)
        amount = to_minor(amount_dec)
        if kind == "adjustment":
            if amount < 0:
                raise AmountError("qoldiq manfiy bo'lishi mumkin emas")
        elif amount <= 0:
            raise AmountError(f"summa noto'g'ri ({a.amount_expr})")

        warnings: list[str] = []
        suspicious = False

        occurred = dates.parse_date(a.date) or today
        if occurred > today:
            warnings.append(f"sana kelajakda: {dates.fmt_date(occurred)}")
            suspicious = True
        elif occurred < today - timedelta(days=366):
            warnings.append(f"sana juda eski: {dates.fmt_date(occurred)}")
            suspicious = True

        who = fam.match_by_name(members, a.member) if a.member else None
        who = who or member

        wallet = fam.match_by_name(wallets, a.wallet) if a.wallet else None
        currency = a.currency
        if not wallet:
            if currency and default_wallet and currency != default_wallet["currency"]:
                wallet = next((w for w in wallets if w["currency"] == currency), None) or default_wallet
            else:
                wallet = default_wallet
        if not wallet:
            raise ValueError("hamyon topilmadi — ⚙️ Sozlamalar → 💼 Hamyonlar orqali qo'shing")
        if not currency:
            currency = wallet["currency"]

        debt = None
        if kind in ("debt_repay_in", "debt_repay_out"):
            direction = "lent" if kind == "debt_repay_in" else "borrowed"
            candidates = [d for d in debts if d["direction"] == direction]
            debt = fam.match_by_name(candidates, a.counterparty, "counterparty") if a.counterparty else None
            if not debt and len(candidates) == 1 and not a.counterparty:
                debt = candidates[0]
            if debt:
                if not a.currency:
                    currency = debt["currency"]
                if currency == debt["currency"] and amount > debt["remaining"]:
                    warnings.append(f"qarz qoldig'i {fmt(debt['remaining'], debt['currency'])}, "
                                    f"qaytarilgani undan {fmt(amount - debt['remaining'], currency)} ko'p")
                    suspicious = True
            else:
                warnings.append(f"«{esc(a.counterparty or '?')}» bo'yicha ochiq qarz topilmadi — "
                                "faqat pul harakati sifatida yozildi")

        rate = await get_rate(self.db, currency, occurred)
        amount_base = convert_minor(amount, rate)
        wallet_rate = rate if wallet["currency"] == currency else await get_rate(self.db, wallet["currency"], occurred)
        wallet_amount = amount if wallet["currency"] == currency else convert_minor(amount, rate, wallet_rate)

        op = Op(kind=kind, amount=amount, currency=currency, rate=rate, amount_base=amount_base,
                occurred_on=occurred, member_id=who["id"], member_name=who["name"],
                description=(a.description or "").strip()[:80],
                wallet_id=wallet["id"], wallet_amount=wallet_amount, wallet_name=wallet["name"],
                wallet_currency=wallet["currency"], note=a.note, warnings=warnings)

        if kind in ("expense", "income"):
            cat = cats.get(a.category or "")
            if not cat or cat["kind"] != kind:
                cat = cats.get("boshqa_chiqim" if kind == "expense" else "boshqa_kirim")
            if cat:
                op.category_id, op.category_key = cat["id"], cat["key"]
                op.category_name, op.category_emoji = cat["name"], cat["emoji"]
            op.description = op.description or (cat["name"] if cat else "Yozuv")
            op.item_key = normalize_name(a.item_key)[:40] or None if a.item_key else None
            op.unit = (a.unit or "").strip()[:10] or None
            if a.quantity:
                try:
                    q = Decimal(str(a.quantity).replace(",", "."))
                    op.quantity = str(q) if q > 0 else None
                except InvalidOperation:
                    op.quantity = None
            if kind == "expense" and a.on_credit:
                op.on_credit = True
                op.wallet_id = op.wallet_amount = None
                op.wallet_name = "Nasiya"
                op.counterparty = (a.counterparty or op.description).strip()[:60]

        elif kind == "transfer":
            to_wallet = fam.match_by_name(wallets, a.to_wallet) if a.to_wallet else None
            to_wallet = to_wallet or wallet
            op.to_wallet_id, op.to_wallet_name, op.to_wallet_currency = to_wallet["id"], to_wallet["name"], to_wallet["currency"]
            if a.to_amount_expr:
                op.to_wallet_amount = parse_minor(a.to_amount_expr)
                if op.to_wallet_amount <= 0:
                    raise AmountError("qabul qilingan summa noto'g'ri")
            elif to_wallet["currency"] == currency:
                op.to_wallet_amount = amount
            else:
                to_rate = await get_rate(self.db, to_wallet["currency"], occurred)
                op.to_wallet_amount = convert_minor(amount, rate, to_rate)
                warnings.append(f"MB kursi bo'yicha hisoblandi: 1 {currency} = {fmt_decimal(rate)} so'm")
            if to_wallet["currency"] != currency and a.to_amount_expr:
                # haqiqiy ayirboshlash kursi
                real_rate = from_minor(op.to_wallet_amount) / amount_dec if amount_dec else Decimal(0)
                op.note = op.note or f"kurs: 1 {currency} = {fmt_decimal(real_rate.quantize(Decimal('0.01')))} {to_wallet['currency']}"
            op.description = op.description or ("O'tkazma" if to_wallet["id"] != wallet["id"] else "Oila ichida berildi")

        elif kind in ("debt_give", "debt_take"):
            op.counterparty = (a.counterparty or "").strip()[:60] or None
            if not op.counterparty:
                raise ValueError("kimga/kimdan qarz ekani aytilmadi")
            op.due_on = dates.parse_date(a.due_date)
            op.description = op.description or (f"{op.counterparty}ga qarz" if kind == "debt_give"
                                                 else f"{op.counterparty}dan qarz")

        elif kind in ("debt_repay_in", "debt_repay_out"):
            op.debt_id = debt["id"] if debt else None
            op.counterparty = (debt["counterparty"] if debt else a.counterparty or "").strip()[:60] or None
            op.description = op.description or ("Qarz qaytdi" if kind == "debt_repay_in" else "Qarz to'landi")

        elif kind == "adjustment":
            current = await ledger.wallet_balance(self.db, member["family_id"], wallet["id"])
            target = amount if currency == wallet["currency"] else wallet_amount
            diff = target - current
            op.currency = wallet["currency"]
            op.rate = wallet_rate
            op.target_balance, op.current_balance = target, current
            op.amount = abs(diff)
            op.wallet_amount = diff
            op.amount_base = convert_minor(abs(diff), wallet_rate)
            op.description = op.description or f"{wallet['name']} qoldig'i tuzatildi"

        # --- shubhali holatlar: avtomatik saqlamaymiz, tasdiq so'raymiz
        base_major = from_minor(op.amount_base)
        if kind in ("expense", "income") and op.currency == "UZS" and base_major < 100:
            warnings.append(f"summa juda kichik: {fmt(op.amount)}")
            suspicious = True
        if kind != "adjustment" and base_major > 1_000_000_000:
            warnings.append(f"summa juda katta: {fmt(op.amount, op.currency)}")
            suspicious = True
        if a.confidence is not None and a.confidence < 0.6:
            suspicious = True
        op.suspicious = suspicious
        return op

    # ================================================================ chek
    def _reconcile_receipt(self, ops: list[Op], result: ParseResult) -> list[str]:
        """Chek: umumiy chegirmani qatorlarga tiyinigacha taqsimlash va jami bilan solishtirish."""
        notes: list[str] = []
        items = [op for op in ops if op.kind == "expense"]
        if not items:
            return notes
        if result.receipt_discount_expr:
            try:
                discount = parse_minor(result.receipt_discount_expr)
            except AmountError:
                discount = 0
            if 0 < discount < sum(op.amount for op in items):
                shares = split_proportionally(discount, [op.amount for op in items])
                for op, share in zip(items, shares):
                    ratio = Decimal(op.amount - share) / Decimal(op.amount)
                    op.amount -= share
                    op.amount_base = convert_minor(op.amount, op.rate)
                    if op.wallet_amount is not None:
                        op.wallet_amount = int((Decimal(op.wallet_amount) * ratio).quantize(Decimal(1)))
                notes.append(f"🏷 Chekdagi {fmt(discount)} chegirma qatorlarga mutanosib taqsimlandi")
        if result.receipt_total_expr:
            try:
                total = parse_minor(result.receipt_total_expr)
            except AmountError:
                return notes
            items_sum = sum(op.amount for op in items)
            if items_sum == total:
                notes.append(f"🧾 Chek jami bilan tekshirildi: <b>{fmt(total)}</b> ✅")
            else:
                diff = items_sum - total
                notes.append(f"🧾 Diqqat: qatorlar yig'indisi {fmt(items_sum)}, chekdagi jami {fmt(total)} "
                             f"(farq {fmt(diff, signed=True)}). Tekshirib, kerak bo'lsa tuzating.")
                for op in items:
                    op.suspicious = True
        return notes

    # ================================================================ saqlash yoki tasdiq
    async def _save_or_confirm(self, member: dict, ops: list[Op], problems: list[str], *, source: str,
                               raw_text: str | None, transcript: str | None, store: str | None) -> Reply:
        if any(op.suspicious for op in ops):
            payload = {"ops": [op.to_json() for op in ops], "source": source, "raw_text": raw_text,
                       "transcript": transcript, "problems": problems, "store": store}
            pending_id = await self.db.execute(
                "INSERT INTO pending (family_id, member_id, payload) VALUES (?,?,?)",
                (member["family_id"], member["id"], json.dumps(payload, ensure_ascii=False)),
            )
            text = self.render_confirm(ops, problems, store)
            return Reply(text, kind="confirm", pending_id=pending_id)
        return await self.commit(member, ops, problems, source=source, raw_text=raw_text,
                                  transcript=transcript, store=store)

    async def commit(self, member: dict, ops: list[Op], problems: list[str], *, source: str,
                      raw_text: str | None, transcript: str | None, store: str | None,
                      title: str = "Yozildi") -> Reply:
        batch_id, tx_ids = await ledger.save_batch(
            self.db, family_id=member["family_id"], member_id=member["id"], source=source,
            raw_text=raw_text, transcript=transcript, ops=ops)
        text, short = await self.render_saved(member, ops, batch_id, problems, store, title=title)
        alerts = await budgets_svc.check_alerts(
            self.db, member["family_id"], {op.category_id for op in ops if op.kind == "expense"})
        if alerts:
            text += "\n\n" + "\n".join(alerts)
        notify = f"👤 <b>{esc(member['name'])}</b> yozdi:\n{short}" if short else None
        if notify and alerts:
            notify += "\n" + "\n".join(alerts)
        return Reply(text, kind="saved", batch_id=batch_id, tx_ids=tx_ids, notify_text=notify, show_undo=True)

    async def confirm_pending(self, member: dict, pending_id: int) -> Reply:
        # Atomar egallash: ikki marta bosilsa ham faqat bittasi saqlaydi
        rows = await self.db.execute_returning(
            "DELETE FROM pending WHERE id=? AND family_id=? RETURNING payload", (pending_id, member["family_id"]))
        if not rows:
            return Reply("Bu yozuv allaqachon saqlangan yoki bekor qilingan.", kind="info")
        payload = json.loads(rows[0]["payload"])
        ops = [Op.from_json(o) for o in payload["ops"]]
        return await self.commit(member, ops, payload.get("problems", []), source=payload.get("source", "text"),
                                  raw_text=payload.get("raw_text"), transcript=payload.get("transcript"),
                                  store=payload.get("store"))

    async def cancel_pending(self, member: dict, pending_id: int) -> bool:
        return await self.db.execute_rowcount(
            "DELETE FROM pending WHERE id=? AND family_id=?", (pending_id, member["family_id"])) > 0

    # ================================================================ ko'rsatish
    def _op_lines(self, op: Op, today: date) -> list[str]:
        when = ""
        if op.occurred_on != today:
            when = f" · <i>{dates.fmt_date(op.occurred_on)}</i>"
        money = f"<b>{fmt(op.amount, op.currency)}</b>"
        if op.currency != "UZS" and op.kind != "adjustment":
            money += f" <i>(≈ {fmt(op.amount_base)})</i>"
        lines: list[str] = []
        if op.kind in ("expense", "income"):
            sign = "" if op.kind == "expense" else "+"
            lines.append(f"{op.category_emoji or '•'} {esc(op.description)} — {sign}{money}{when}")
            if op.quantity and Decimal(op.quantity) != 1:
                qty = Decimal(op.quantity)
                unit_price = (Decimal(op.amount) / qty).quantize(Decimal(1))
                lines.append(f"     <i>{fmt_decimal(qty)} {esc(op.unit or 'ta')} × {fmt(int(unit_price), op.currency)}</i>")
            if op.on_credit:
                lines.append(f"     📝 nasiya — {esc(op.counterparty)}ga qarz ochildi")
        elif op.kind == "transfer":
            lines.append(f"🔁 {esc(op.description)} — {money}{when}")
            if op.to_wallet_id != op.wallet_id:
                to_money = ""
                if op.to_wallet_currency != op.currency:
                    to_money = f" ({fmt(op.to_wallet_amount, op.to_wallet_currency)})"
                lines.append(f"     <i>{esc(op.wallet_name)} → {esc(op.to_wallet_name)}{to_money}</i>")
        elif op.kind in ("debt_give", "debt_take"):
            lines.append(f"{KIND_EMOJI[op.kind]} {esc(op.description)} — {money}{when}")
            if op.due_on:
                lines.append(f"     <i>qaytarish muddati: {dates.fmt_date(op.due_on)}</i>")
        elif op.kind in ("debt_repay_in", "debt_repay_out"):
            lines.append(f"{KIND_EMOJI[op.kind]} {esc(op.description)} — {money}{when}")
        elif op.kind == "adjustment":
            cur = op.wallet_currency
            if op.wallet_amount == 0:
                lines.append(f"⚖️ {esc(op.wallet_name)}: hisob va haqiqat bir xil — <b>{fmt(op.target_balance, cur)}</b> ✅")
            else:
                lines.append(f"⚖️ {esc(op.wallet_name)} qoldig'i tekshirildi")
                lines.append(f"     hisobda: {fmt(op.current_balance, cur)}")
                lines.append(f"     aslida: <b>{fmt(op.target_balance, cur)}</b>")
                lines.append(f"     tuzatildi: <b>{fmt(op.wallet_amount, cur, signed=True)}</b>")
        if op.note:
            lines.append(f"     💬 <i>{esc(op.note)}</i>")
        for w in op.warnings:
            lines.append(f"     ⚠️ <i>{w}</i>")
        return lines

    async def render_saved(self, member: dict, ops: list[Op], batch_id: int, problems: list[str],
                           store: str | None, title: str = "Yozildi") -> tuple[str, str]:
        today = dates.today()
        family_id = member["family_id"]
        body: list[str] = []
        expenses = [op for op in ops if op.kind == "expense"]
        money_ops = [op for op in ops if op.kind in ("expense", "income")]
        wallets_used = {op.wallet_name for op in money_ops if op.wallet_name}
        per_line_wallet = len(wallets_used) > 1 or len(expenses) <= 1
        for op in ops:
            op_lines = self._op_lines(op, today)
            if op.member_id != member["id"] and op.kind in ("expense", "income") and op.member_name:
                op_lines[0] += f" · 👤 {esc(op.member_name)}"
            if per_line_wallet and op.kind in ("expense", "income") and op.wallet_name and not op.on_credit:
                op_lines[0] += f" · <i>{esc(op.wallet_name)}</i>"
            body += op_lines
            if op.kind in ("debt_repay_in", "debt_repay_out") and op.debt_id:
                debt = await ledger.get_debt(self.db, family_id, op.debt_id)
                if debt and debt["remaining"] > 0:
                    body.append(f"     <i>qolgan qarz: {fmt(debt['remaining'], debt['currency'])}</i>")
                elif debt:
                    body.append("     🎉 <i>qarz to'liq yopildi</i>")
            # narx xotirasi
            if op.kind == "expense" and op.item_key:
                prev = await ledger.last_price(self.db, family_id, op.item_key, exclude_batch=batch_id)
                change = _price_change_line(op, prev)
                if change:
                    body.append(change)
        head = f"✅ <b>{title}</b>" + (f" · {esc(store)}" if store else "")
        out = [head, ""] + body
        if len(expenses) > 1:
            total = sum(op.amount_base for op in expenses)
            out += [LINE, f"Jami chiqim: <b>{fmt(total)}</b>"]
            if not per_line_wallet and wallets_used:
                out[-1] += f" · <i>{esc(next(iter(wallets_used)))}</i>"
        if problems:
            out += [""] + problems
        if expenses or any(op.kind == "income" for op in ops):
            day = await reports.aggregate(self.db, family_id, today, today, kinds=("expense",))
            month = await reports.aggregate(self.db, family_id, dates.month_start(today), today, kinds=("expense",))
            out += ["", f"📅 Bugun: {fmt(day.expense)} · {dates.MONTHS_TITLE[today.month - 1]}: {fmt(month.expense)}"]
        short = "\n".join(body)
        return "\n".join(out), short

    def render_confirm(self, ops: list[Op], problems: list[str], store: str | None) -> str:
        today = dates.today()
        out = ["🧐 <b>Tekshirib oling</b>" + (f" · {esc(store)}" if store else ""),
               "<i>Ba'zi joylar shubhali ko'rindi, saqlashdan oldin tasdiqlang:</i>", ""]
        for op in ops:
            out += self._op_lines(op, today)
        expenses = [op for op in ops if op.kind == "expense"]
        if len(expenses) > 1:
            out += [LINE, f"Jami chiqim: <b>{fmt(sum(op.amount_base for op in expenses))}</b>"]
        if problems:
            out += [""] + problems
        out += ["", "To'g'ri bo'lsa ✅ ni bosing. Xato bo'lsa — shu xabarga javob (reply) qilib tuzatishni yozing."]
        return "\n".join(out)

    # ================================================================ sozlash amallari
    async def _apply_config(self, member: dict, a: Action) -> Reply:
        family_id = member["family_id"]
        try:
            amount = parse_minor(a.amount_expr)
        except AmountError:
            return Reply("🤔 Summani tushunmadim. Masalan: <i>oziq-ovqatga oyiga 3 mln limit</i>", kind="question")
        cat = await fam.category_by_key(self.db, family_id, a.category) if a.category else None
        if a.type == "budget_set":
            if a.currency and a.currency != "UZS":
                rate = await get_rate(self.db, a.currency, dates.today())
                amount = convert_minor(amount, rate)
            await budgets_svc.set_budget(self.db, family_id, cat["id"] if cat else None, amount)
            name = f"{cat['emoji']} {esc(cat['name'])}" if cat else "🧮 Umumiy oylik"
            if amount <= 0:
                return Reply(f"🗑 {name} limiti olib tashlandi.", kind="info")
            status = [b for b in await budgets_svc.budget_status(self.db, family_id)
                      if b["category_id"] == (cat["id"] if cat else None)]
            text = f"🎯 <b>Limit o'rnatildi</b>\n{name}: <b>{fmt(amount)}</b> / oyiga"
            if status:
                text += "\n\n" + budgets_svc.render_budget_line(status[0])
            return Reply(text, kind="info")
        # recurring_add
        day = a.day_of_month or dates.today().day
        default = await fam.default_wallet(self.db, family_id, member)
        wallet = fam.match_by_name(await fam.wallets(self.db, family_id), a.wallet) if a.wallet else default
        rec_kind = "income" if cat and cat["kind"] == "income" else "expense"
        await budgets_svc.add_recurring(
            self.db, family_id, kind=rec_kind, description=(a.description or (cat["name"] if cat else "To'lov"))[:80],
            amount=amount, currency=a.currency or "UZS", category_id=cat["id"] if cat else None,
            wallet_id=wallet["id"] if wallet else None, member_id=member["id"], day_of_month=day)
        nxt = budgets_svc.next_due_date(day, dates.today())
        return Reply(f"🔔 <b>Eslatma qo'shildi</b>\n{esc(a.description or '')}: {fmt(amount, a.currency or 'UZS')}, "
                     f"har oyning {day}-sanasida.\nKeyingisi: {dates.fmt_date(nxt)}. "
                     f"O'sha kuni «To'landi» tugmasini bossangiz, o'zim yozib qo'yaman.", kind="info")

    # ================================================================ savollar
    async def answer_query(self, member: dict, a: Action, question: str) -> Reply:
        if not a.query:
            return Reply("🤔 Savolni tushunmadim, boshqacharoq so'rab ko'ring.", kind="question")
        facts = await queries.run(self.db, member["family_id"], a.query)
        try:
            text = await self.ai.answer(question, facts, member_id=member["id"])
        except AIError:
            text = queries.fallback_text(facts)
        return Reply(_sanitize_html(text), kind="info")

    # ================================================================ bekor qilish / tuzatish
    async def undo_last(self, member: dict) -> Reply:
        batch = await ledger.last_batch(self.db, member["family_id"], member["id"])
        if not batch:
            return Reply("Bekor qiladigan yozuv topilmadi.", kind="info")
        txs = await ledger.batch_transactions(self.db, member["family_id"], batch["id"])
        await ledger.delete_batch(self.db, member["family_id"], batch["id"])
        names = ", ".join(f"{t['description']} ({fmt(t['amount'], t['currency'])})" for t in txs[:6])
        return Reply(f"↩️ Bekor qilindi: {esc(names)}", kind="info", batch_id=batch["id"])

    async def correct(self, member: dict, link: dict, correction: str) -> list[Reply]:
        """Foydalanuvchi bot xabariga javob (reply) qilib tuzatish yozdi."""
        family_id = member["family_id"]
        context = await build_context(self.db, member)
        if link.get("pending_id"):
            row = await self.db.fetchone("SELECT * FROM pending WHERE id=? AND family_id=?",
                                         (link["pending_id"], family_id))
            if not row:
                return [Reply("Bu yozuv allaqachon saqlangan yoki bekor qilingan.", kind="info")]
            payload = json.loads(row["payload"])
            old_ops = [Op.from_json(o) for o in payload["ops"]]
            entries = [_op_to_entry(i, op) for i, op in enumerate(old_ops, 1)]
        else:
            if link.get("tx_id_list"):
                txs = await ledger.transactions_by_ids(self.db, family_id, link["tx_id_list"])
            else:
                txs = await ledger.batch_transactions(self.db, family_id, link["batch_id"])
            txs = [t for t in txs if t["kind"] != "adjustment"]
            if not txs:
                return [Reply("Bu yozuv o'chirilgan, tuzatadigan narsa qolmadi.", kind="info")]
            entries = [_tx_to_entry(i, t) for i, t in enumerate(txs, 1)]
        try:
            result = await self.ai.correct(context, entries, correction, member_id=member["id"])
        except AIError:
            return [Reply(AI_DOWN_TEXT, kind="error")]
        if result.reply_text and "NOT_A_CORRECTION" in result.reply_text:
            return await self.handle(member, text=correction)
        if result.needs_clarification and result.clarification_question:
            return [Reply("🤔 " + esc(result.clarification_question), kind="question")]
        record = [a for a in result.actions if a.type in RECORD_TYPES and a.type != "balance_set"]
        ops, problems = await self.prepare_ops(member, record)
        if problems and not ops and record:
            return [Reply("🤔 " + "\n".join(problems), kind="question")]

        if link.get("pending_id"):
            payload["ops"] = [op.to_json() for op in ops]
            payload["problems"] = problems
            await self.db.execute("UPDATE pending SET payload=? WHERE id=?",
                                  (json.dumps(payload, ensure_ascii=False), link["pending_id"]))
            if not ops:
                await self.cancel_pending(member, link["pending_id"])
                return [Reply("🗑 Hammasi olib tashlandi, hech narsa saqlanmadi.", kind="info")]
            return [Reply(self.render_confirm(ops, problems, payload.get("store")), kind="confirm",
                          pending_id=link["pending_id"])]

        batch_id = txs[0]["batch_id"]
        old_ids = [t["id"] for t in txs]
        new_ids = await ledger.replace_transactions(self.db, family_id, batch_id, old_ids, member["id"], ops)
        if not ops:
            return [Reply("🗑 Yozuv o'chirildi.", kind="info")]
        text, short = await self.render_saved(member, ops, batch_id, problems, None, title="Tuzatildi")
        return [Reply(text, kind="saved", batch_id=batch_id, tx_ids=new_ids, show_undo=False,
                      notify_text=f"✏️ <b>{esc(member['name'])}</b> tuzatdi:\n{short}")]


# ==================================================================== yordamchilar

def unit_key(unit: str | None) -> str:
    """'ta', 'dona' va birliksiz - hammasi bir xil: donalab."""
    u = (unit or "").strip().lower()
    return "" if u in ("ta", "dona", "shtuk", "sht") else u


def _price_change_line(op: Op, prev: dict | None) -> str | None:
    if not prev or prev["currency"] != op.currency or unit_key(prev["unit"]) != unit_key(op.unit):
        return None
    try:
        q_now = Decimal(op.quantity) if op.quantity else Decimal(1)
        q_prev = Decimal(prev["quantity"]) if prev["quantity"] else Decimal(1)
    except InvalidOperation:
        return None
    if q_now <= 0 or q_prev <= 0:
        return None
    now_price = int((Decimal(op.amount) / q_now).quantize(Decimal(1)))
    prev_price = int((Decimal(prev["amount"]) / q_prev).quantize(Decimal(1)))
    if prev_price == now_price or prev_price == 0:
        return None
    pct = percent(now_price - prev_price, prev_price)
    if abs(pct) > 60:
        return None  # bunday katta farq - deyarli har doim boshqa mahsulot/o'lcham, narx o'zgarishi emas
    arrow = "📈 qimmatlagan" if now_price > prev_price else "📉 arzonlagan"
    unit = f"/{op.unit}" if op.unit and op.unit not in ("ta", "dona") else ""
    when = dates.fmt_date(date.fromisoformat(prev["occurred_on"]))
    return (f"     {arrow}: oldin {fmt(prev_price, op.currency)}{unit} edi ({when}), "
            f"{fmt_percent(pct, signed=True)}")


def _tx_to_entry(ref: int, t: dict) -> dict:
    entry = {
        "ref": ref, "type": t["kind"], "description": t["description"], "item_key": t["item_key"],
        "amount_expr": format(from_minor(t["amount"]).normalize(), "f"), "currency": t["currency"],
        "quantity": t["quantity"], "unit": t["unit"], "category": t["category_key"],
        "member": t["member_name"], "wallet": t["wallet_name"], "to_wallet": t["to_wallet_name"],
        "date": t["occurred_on"], "counterparty": t["counterparty"], "on_credit": bool(t["on_credit"]),
    }
    if t["kind"] == "transfer" and t["to_wallet_currency"] and t["to_wallet_currency"] != t["currency"]:
        entry["to_amount_expr"] = format(from_minor(t["to_wallet_amount"]).normalize(), "f")
    return entry


def _op_to_entry(ref: int, op: Op) -> dict:
    entry = {
        "ref": ref, "type": op.kind, "description": op.description, "item_key": op.item_key,
        "amount_expr": format(from_minor(op.amount).normalize(), "f"), "currency": op.currency,
        "quantity": op.quantity, "unit": op.unit, "category": op.category_key or None,
        "member": op.member_name, "wallet": op.wallet_name if op.wallet_id else None,
        "to_wallet": op.to_wallet_name or None, "date": op.occurred_on.isoformat(),
        "counterparty": op.counterparty, "on_credit": op.on_credit,
        "due_date": op.due_on.isoformat() if op.due_on else None,
    }
    if op.kind == "transfer" and op.to_wallet_currency != op.currency and op.to_wallet_amount:
        entry["to_amount_expr"] = format(from_minor(op.to_wallet_amount).normalize(), "f")
    return entry


_ALLOWED_TAGS = ("b", "i", "u", "s", "code")


def _sanitize_html(text: str) -> str:
    """AI matnidagi ruxsat etilmagan HTML ni zararsizlantiradi (Telegram parse xatosining oldini oladi)."""
    import re
    text = text.replace("**", "").replace("<br>", "\n").replace("<br/>", "\n")
    placeholder = {}

    def keep(m):
        key = f"\x00{len(placeholder)}\x00"
        placeholder[key] = m.group(0)
        return key

    pattern = r"</?(?:" + "|".join(_ALLOWED_TAGS) + r")>"
    text = re.sub(pattern, keep, text)
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    for key, tag in placeholder.items():
        text = text.replace(key, tag)
    # yopilmagan teglarni tekshirish
    for tag in _ALLOWED_TAGS:
        if text.count(f"<{tag}>") != text.count(f"</{tag}>"):
            text = text.replace(f"<{tag}>", "").replace(f"</{tag}>", "")
    return text
