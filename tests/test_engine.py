"""Dvigatel va buxgalteriya testlari (AI o'rniga soxta javoblar - tarmoqsiz, aniq)."""
from datetime import timedelta

from hamyon.ai.schemas import ParseResult
from hamyon.core import dates
from hamyon.services import budgets, ledger, reports
from hamyon.services.ai_actions import make_action
from hamyon.services.engine import Engine


def result(*actions, **kw) -> ParseResult:
    base = dict(transcript=None, actions=list(actions), needs_clarification=False, clarification_question=None,
                reply_text=None, receipt_total_expr=None, receipt_discount_expr=None, receipt_store=None)
    base.update(kw)
    return ParseResult(**base)


class FakeAI:
    def __init__(self):
        self.next: ParseResult | None = None
        self.answer_text = "javob"

    async def parse(self, *a, **kw):
        return self.next

    async def correct(self, *a, **kw):
        return self.next

    async def answer(self, question, facts, member_id=None):
        self.facts = facts
        return self.answer_text

    async def insight(self, facts):
        return "• xulosa"


def A(type_, expr, **kw):
    return make_action(type=type_, amount_expr=expr, **kw)


async def run(engine, member, res, source="text"):
    return await engine.process_result(member, res, source=source, raw_text="test")


async def balances(db, hh):
    b = await ledger.wallet_balances(db, hh["family_id"])
    return {name: b.get(w["id"], 0) for name, w in hh["wallets"].items()}


async def test_expense_items_exact(db, household):
    eng = Engine(db, FakeAI())
    me = household["rustam"]
    replies = await run(eng, me, result(
        A("expense", "2*4500", description="Non", category="oziq_ovqat", quantity="2", unit="ta", item_key="non"),
        A("expense", "12000", description="Sut", category="oziq_ovqat"),
        A("expense", "87500", description="Dori", category="salomatlik", member="Malika"),
    ))
    assert replies[0].kind == "saved"
    assert "108 500 so'm" in replies[0].text
    bal = await balances(db, household)
    assert bal["Naqd"] == -10850000
    rows = await ledger.batch_transactions(db, household["family_id"], replies[0].batch_id)
    assert [r["member_name"] for r in rows] == ["Aziz", "Aziz", "Malika"]


async def test_unknown_category_falls_back(db, household):
    eng = Engine(db, FakeAI())
    replies = await run(eng, household["rustam"], result(A("expense", "5000", description="X", category="yoq_narsa")))
    rows = await ledger.batch_transactions(db, household["family_id"], replies[0].batch_id)
    assert rows[0]["category_key"] == "boshqa_chiqim"


async def test_usd_expense_uses_usd_wallet_and_rate(db, household):
    eng = Engine(db, FakeAI())
    replies = await run(eng, household["rustam"], result(A("expense", "50", currency="USD", description="Kurtka",
                                                             category="kiyim")))
    rows = await ledger.batch_transactions(db, household["family_id"], replies[0].batch_id)
    assert rows[0]["wallet_name"] == "Dollar"
    assert rows[0]["amount"] == 5000 and rows[0]["amount_base"] == 60000000  # 50 * 12000 so'm
    bal = await balances(db, household)
    assert bal["Dollar"] == -5000


async def test_fx_exchange_real_rate(db, household):
    eng = Engine(db, FakeAI())
    await run(eng, household["rustam"], result(A("transfer", "200", currency="USD", wallet="Dollar",
                                                  to_wallet="Naqd", to_amount_expr="2540000",
                                                  description="Ayirboshlash")))
    bal = await balances(db, household)
    assert bal["Dollar"] == -20000
    assert bal["Naqd"] == 254000000
    # transfer daromad/xarajat emas
    t = dates.today()
    agg = await reports.aggregate(db, household["family_id"], t, t)
    assert agg.expense == 0 and agg.income == 0


async def test_debt_lifecycle(db, household):
    eng = Engine(db, FakeAI())
    me = household["rustam"]
    await run(eng, me, result(A("debt_give", "500000", counterparty="Akmal")))
    debts = await ledger.open_debts(db, household["family_id"])
    assert len(debts) == 1 and debts[0]["remaining"] == 50000000
    r1 = await run(eng, me, result(A("debt_repay_in", "200000", counterparty="akmal")))
    assert "qolgan qarz: 300 000 so'm" in r1[0].text
    r2 = await run(eng, me, result(A("debt_repay_in", "300000", counterparty="Akmal aka")))
    assert "to'liq yopildi" in r2[0].text
    assert await ledger.open_debts(db, household["family_id"]) == []
    # qaytarishni bekor qilsak - qarz qayta ochiladi
    await ledger.delete_batch(db, household["family_id"], r2[0].batch_id)
    debts = await ledger.open_debts(db, household["family_id"])
    assert debts[0]["remaining"] == 30000000
    # naqd: -500 000 + 200 000 = -300 000
    assert (await balances(db, household))["Naqd"] == -30000000


async def test_overpay_debt_needs_confirmation(db, household):
    eng = Engine(db, FakeAI())
    me = household["rustam"]
    await run(eng, me, result(A("debt_give", "100000", counterparty="Akmal")))
    replies = await run(eng, me, result(A("debt_repay_in", "150000", counterparty="Akmal")))
    assert replies[0].kind == "confirm"


async def test_on_credit_expense(db, household):
    eng = Engine(db, FakeAI())
    me = household["rustam"]
    await run(eng, me, result(A("expense", "340000", description="Makro", category="oziq_ovqat", on_credit=True,
                                counterparty="Makro")))
    bal = await balances(db, household)
    assert bal["Naqd"] == 0  # pul chiqmadi
    debts = await ledger.open_debts(db, household["family_id"])
    assert debts[0]["direction"] == "borrowed" and debts[0]["remaining"] == 34000000
    t = dates.today()
    assert (await reports.aggregate(db, household["family_id"], t, t)).expense == 34000000
    # qarzni to'lash: hamyondan chiqadi, lekin xarajat emas (ikki marta sanalmaydi)
    await run(eng, me, result(A("debt_repay_out", "340000", counterparty="Makro")))
    assert (await balances(db, household))["Naqd"] == -34000000
    assert (await reports.aggregate(db, household["family_id"], t, t)).expense == 34000000
    assert await ledger.open_debts(db, household["family_id"]) == []


async def test_balance_set_adjusts_difference(db, household):
    eng = Engine(db, FakeAI())
    me = household["rustam"]
    await run(eng, me, result(A("income", "1000000", category="maosh", wallet="Karta")))
    await run(eng, me, result(A("expense", "186400", category="kommunal", wallet="Karta")))
    replies = await run(eng, me, result(A("balance_set", "800000", wallet="Karta")))
    assert "+(-" not in replies[0].text
    assert (await balances(db, household))["Karta"] == 80000000
    # qayta tekshirsa - farq yo'q, yozuv yaratilmaydi
    replies = await run(eng, me, result(A("balance_set", "800000", wallet="Karta")))
    assert "bir xil" in replies[0].text
    # tuzatish hisobotga kirmaydi
    t = dates.today()
    agg = await reports.aggregate(db, household["family_id"], t, t)
    assert agg.expense == 18640000 and agg.income == 100000000


async def test_suspicious_small_amount_confirm_flow(db, household):
    eng = Engine(db, FakeAI())
    me = household["rustam"]
    replies = await run(eng, me, result(A("expense", "12", description="Non", category="oziq_ovqat")))
    assert replies[0].kind == "confirm"
    assert (await balances(db, household))["Naqd"] == 0
    saved = await eng.confirm_pending(me, replies[0].pending_id)
    assert saved.kind == "saved"
    assert (await balances(db, household))["Naqd"] == -1200
    again = await eng.confirm_pending(me, replies[0].pending_id)
    assert "allaqachon" in again.text


async def test_future_date_needs_confirm(db, household):
    eng = Engine(db, FakeAI())
    future = (dates.today() + timedelta(days=5)).isoformat()
    replies = await run(eng, household["rustam"], result(A("expense", "5000", date=future, category="kafe")))
    assert replies[0].kind == "confirm"


async def test_receipt_discount_split_to_tiyin(db, household):
    eng = Engine(db, FakeAI())
    res = result(
        A("expense", "33333", description="A", category="oziq_ovqat"),
        A("expense", "33333", description="B", category="oziq_ovqat"),
        A("expense", "33334", description="C", category="uy"),
        receipt_discount_expr="10000", receipt_total_expr="90000", receipt_store="Korzinka",
    )
    replies = await run(eng, household["rustam"], res, source="photo")
    assert replies[0].kind == "saved", replies[0].text
    assert "tekshirildi" in replies[0].text
    rows = await ledger.batch_transactions(db, household["family_id"], replies[0].batch_id)
    assert sum(r["amount"] for r in rows) == 9000000
    assert (await balances(db, household))["Naqd"] == -9000000


async def test_receipt_total_mismatch_requires_confirm(db, household):
    eng = Engine(db, FakeAI())
    res = result(A("expense", "10000", description="A"), A("expense", "5000", description="B"),
                 receipt_total_expr="16000")
    replies = await run(eng, household["rustam"], res, source="photo")
    assert replies[0].kind == "confirm"
    assert "farq" in replies[0].text


async def test_correction_replaces_records(db, household):
    ai = FakeAI()
    eng = Engine(db, ai)
    me = household["rustam"]
    replies = await run(eng, me, result(A("expense", "12000", description="Sut", category="oziq_ovqat"),
                                        A("expense", "6000", description="Non", category="oziq_ovqat")))
    batch_id = replies[0].batch_id
    ai.next = result(A("expense", "15000", description="Sut", category="oziq_ovqat", wallet="Karta"))
    fixed = await eng.correct(me, {"batch_id": batch_id, "tx_id_list": [], "pending_id": None}, "sut 15 ming edi, kartadan, nonni o'chir")
    assert fixed[0].kind == "saved"
    rows = await ledger.batch_transactions(db, household["family_id"], batch_id)
    assert [(r["description"], r["amount"], r["wallet_name"]) for r in rows] == [("Sut", 1500000, "Karta")]
    bal = await balances(db, household)
    assert bal["Naqd"] == 0 and bal["Karta"] == -1500000


async def test_undo_last_and_redo(db, household):
    eng = Engine(db, FakeAI())
    me = household["rustam"]
    r = await run(eng, me, result(A("expense", "50000", category="kafe")))
    undo = await eng.undo_last(me)
    assert "Bekor qilindi" in undo.text
    assert (await balances(db, household))["Naqd"] == 0
    await ledger.restore_batch(db, household["family_id"], r[0].batch_id)
    assert (await balances(db, household))["Naqd"] == -5000000


async def test_budget_alert_once(db, household):
    eng = Engine(db, FakeAI())
    me = household["rustam"]
    r = await run(eng, me, result(make_action(type="budget_set", amount_expr="100000", category="kafe")))
    assert "Limit o'rnatildi" in r[0].text
    r = await run(eng, me, result(A("expense", "85000", category="kafe")))
    assert "85%" in r[0].text
    r = await run(eng, me, result(A("expense", "1000", category="kafe")))
    assert "limit" not in r[0].text.lower()
    r = await run(eng, me, result(A("expense", "20000", category="kafe")))
    assert "limiti tugadi" in r[0].text
    status = await budgets.budget_status(db, household["family_id"])
    assert status[0]["spent"] == 10600000


async def test_price_memory(db, household):
    eng = Engine(db, FakeAI())
    me = household["rustam"]
    await run(eng, me, result(A("expense", "2*4000", description="Non", quantity="2", unit="ta", item_key="non",
                                category="oziq_ovqat")))
    r = await run(eng, me, result(A("expense", "4500", description="Non", item_key="non", category="oziq_ovqat")))
    assert "qimmatlagan" in r[0].text and "+12,5%" in r[0].text


async def test_query_facts_are_code_computed(db, household):
    ai = FakeAI()
    eng = Engine(db, ai)
    me = household["rustam"]
    await run(eng, me, result(A("expense", "100000", category="oziq_ovqat"), A("expense", "50000", category="kafe"),
                              A("income", "1000000", category="maosh")))
    t = dates.today()
    q = make_action(type="query", query={
        "focus": "both", "date_from": dates.month_start(t).isoformat(), "date_to": t.isoformat(),
        "compare_from": None, "compare_to": None, "categories": [], "members": [], "search": None,
        "group_by": "category"})
    await run(eng, me, result(q))
    assert ai.facts["expense_total"] == "150 000 so'm"
    assert ai.facts["income_total"] == "1 000 000 so'm"
    assert ai.facts["net_income_minus_expense"] == "+850 000 so'm"


async def test_ai_answer_html_sanitized(db, household):
    ai = FakeAI()
    ai.answer_text = "**Jami** <b>5 000</b> <script>x</script> 3 < 5"
    eng = Engine(db, ai)
    q = make_action(type="query", query={"focus": "balances", "date_from": None, "date_to": None,
                                         "compare_from": None, "compare_to": None, "categories": [],
                                         "members": [], "search": None, "group_by": "none"})
    r = await run(eng, household["rustam"], result(q))
    assert "<script>" not in r[0].text and "&lt;script&gt;" in r[0].text and "<b>5 000</b>" in r[0].text


async def test_reports_chart_and_excel(db, household):
    from hamyon.services import charts, export
    eng = Engine(db, FakeAI())
    me = household["rustam"]
    await run(eng, me, result(A("expense", "100000", category="oziq_ovqat"), A("income", "500000", category="maosh"),
                              A("expense", "30", currency="USD", category="kiyim")))
    t = dates.today()
    s = dates.month_start(t)
    text = await reports.period_report_text(db, household["family_id"], s, t, "Shu oy")
    assert "Oziq-ovqat" in text and "Kirim" in text
    agg = await reports.aggregate(db, household["family_id"], s, t)
    png = await charts.report_chart(agg)
    assert png[:4] == b"\x89PNG"
    xlsx = await export.build_xlsx(db, household["family_id"], s, t)
    assert xlsx[:2] == b"PK"
    digest = await reports.daily_digest_text(db, household["family_id"], t)
    assert "Kun yakuni" in digest
