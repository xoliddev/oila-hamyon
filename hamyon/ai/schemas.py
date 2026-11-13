"""AI javobining qat'iy tuzilmasi (Gemini structured output)."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

ActionType = Literal[
    "expense",          # chiqim
    "income",           # kirim
    "transfer",         # hamyonlar orasida o'tkazma / valyuta ayirboshlash / bankomatdan yechish
    "debt_give",        # biz birovga qarz berdik
    "debt_take",        # biz birovdan qarz oldik (pul qo'limizga keldi)
    "debt_repay_in",    # bizga qarz qaytarishdi
    "debt_repay_out",   # biz qarzimizni qaytardik
    "balance_set",      # "kartamda hozir X bor" - hamyon qoldig'ini tekshirish/to'g'rilash
    "budget_set",       # oylik limit
    "recurring_add",    # har oy takrorlanadigan to'lov eslatmasi
    "query",            # savol / hisobot so'rash
    "undo",             # oxirgi yozuvni bekor qilish
    "chat",             # salomlashish, rahmat, yordam so'rash, bot haqida savol
]

Currency = Literal["UZS", "USD", "EUR", "RUB"]


class QuerySpec(BaseModel):
    focus: Literal["expense", "income", "both", "balances", "debts", "budgets", "prices", "transactions"] = Field(
        description="Savol nimaga qaratilgan")
    date_from: Optional[str] = Field(description="YYYY-MM-DD, davr boshi")
    date_to: Optional[str] = Field(description="YYYY-MM-DD, davr oxiri (kiritilgan)")
    compare_from: Optional[str] = Field(description="Taqqoslash davri boshi, YYYY-MM-DD yoki null")
    compare_to: Optional[str] = Field(description="Taqqoslash davri oxiri, YYYY-MM-DD yoki null")
    categories: list[str] = Field(description="Kategoriya kalitlari (key), bo'sh = hammasi")
    members: list[str] = Field(description="Oila a'zolari ismlari, bo'sh = hammasi")
    search: Optional[str] = Field(description="Mahsulot/izoh bo'yicha qidiruv so'zi (item_key shaklida), masalan 'sut'")
    group_by: Literal["category", "member", "day", "month", "item", "wallet", "none"] = Field(
        description="Natijani nima bo'yicha guruhlash")


class Action(BaseModel):
    type: ActionType
    description: Optional[str] = Field(description="Qisqa, aniq nom, o'zbek lotinida, bosh harf bilan: 'Non', 'Svet uchun to'lov'")
    item_key: Optional[str] = Field(description="Mahsulot/xizmatning normal kaliti: kichik harf, lotin, birlik shaklida, apostrofsiz: 'non', 'sut', 'gosht', 'benzin', 'svet'")
    amount_expr: Optional[str] = Field(description="Faqat raqamlar va + - * / ( ) . dan iborat ifoda, to'liq birlikda: '12000', '2*9500', '1500000', '45.5'")
    currency: Optional[Currency]
    quantity: Optional[str] = Field(description="Miqdor raqam sifatida: '2', '1.5', '0.5' yoki null")
    unit: Optional[str] = Field(description="O'lchov birligi: 'kg', 'g', 'l', 'ta', 'dona', 'qop', 'quti', 'm' yoki null")
    category: Optional[str] = Field(description="Kategoriya kaliti (key) - faqat berilgan ro'yxatdan")
    member: Optional[str] = Field(description="Kim uchun / kimning puli - oila a'zosining ismi aynan ro'yxatdagidek, yoki null (= yozayotgan odam)")
    wallet: Optional[str] = Field(description="Hamyon nomi aynan ro'yxatdagidek yoki null (= standart)")
    to_wallet: Optional[str] = Field(description="transfer uchun: qaysi hamyonga")
    to_amount_expr: Optional[str] = Field(description="transfer boshqa valyutaga bo'lsa: qabul qilingan summa ifodasi")
    date: Optional[str] = Field(description="YYYY-MM-DD; foydalanuvchi sana aytmasa null (= bugun)")
    counterparty: Optional[str] = Field(description="Qarzlar uchun: qarshi tomon (odam/do'kon) nomi")
    on_credit: Optional[bool] = Field(description="expense nasiyaga (pul to'lanmay, qarzga) olingan bo'lsa true")
    due_date: Optional[str] = Field(description="Qarz qaytarish muddati YYYY-MM-DD yoki null")
    day_of_month: Optional[int] = Field(description="recurring_add uchun: oyning qaysi kuni (1-31)")
    query: Optional[QuerySpec]
    confidence: float = Field(description="0..1 - shu harakatni to'g'ri tushunganingga ishonch")
    note: Optional[str] = Field(description="Faqat foydalanuvchiga ko'rsatiladigan muhim izoh/taxmin, o'zbekcha, qisqa. Odatda null")


class ParseResult(BaseModel):
    transcript: Optional[str] = Field(description="Ovozli xabar bo'lsa - aytilganlarning aynan matni; aks holda null")
    actions: list[Action]
    needs_clarification: bool = Field(description="Muhim ma'lumot (summa) yetishmasa yoki ma'no butunlay noaniq bo'lsa true")
    clarification_question: Optional[str] = Field(description="Aniqlashtiruvchi bitta qisqa savol, o'zbekcha")
    reply_text: Optional[str] = Field(description="Faqat 'chat' turi uchun: qisqa samimiy javob")
    receipt_total_expr: Optional[str] = Field(description="Chek rasmi bo'lsa: chekdagi YAKUNIY to'langan summa ifodasi")
    receipt_discount_expr: Optional[str] = Field(description="Chekda umumiy chegirma bo'lsa uning summasi (musbat), aks holda null")
    receipt_store: Optional[str] = Field(description="Chek bo'lsa: do'kon nomi")


class Insight(BaseModel):
    text: str = Field(description="Telegram HTML formatidagi tayyor matn")
