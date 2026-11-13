"""Foydalanuvchiga ko'rinadigan doimiy matnlar."""

BTN_REPORT = "📊 Hisobot"
BTN_BALANCE = "💼 Balans"
BTN_HISTORY = "📒 Tarix"
BTN_DEBTS = "🤝 Qarzlar"
BTN_BUDGET = "🎯 Limitlar"
BTN_SETTINGS = "⚙️ Sozlamalar"
BTN_RECURRING = "🔔 Oylik to'lovlar"
BTN_UNDO = "↩️ Oxirgisini bekor qilish"
BTN_HELP = "📖 Yordam"
MENU_BUTTONS = {BTN_REPORT, BTN_BALANCE, BTN_HISTORY, BTN_DEBTS, BTN_BUDGET, BTN_SETTINGS, BTN_RECURRING,
                BTN_UNDO, BTN_HELP}

NOT_MEMBER = (
    "👋 Assalomu alaykum! Bu — bitta oilaning shaxsiy hisob-kitob boti.\n\n"
    "Qo'shilish uchun oila boshlig'idan <b>taklif havolasini</b> so'rang."
)

ASK_NAME = "Keling tanishamiz 🙂\nSizni qanday chaqiraylik? Ismingizni yozing yoki pastdagi tugmani bosing."
ASK_ROLE = "Oilada kimsiz? Bu menga «onam», «ukam» kabi so'zlarni to'g'ri tushunishga yordam beradi."

WELCOME = """✨ <b>Xush kelibsiz, {name}!</b>

Men — oilangizning shaxsiy hisobchisiman. Hech qanday forma, tugma shart emas — shunchaki <b>odamga aytgandek yozing</b> yoki <b>ovozli xabar</b> yuboring:

🛒 <i>non 2 ta 4500 dan, sut 12 ming</i>
💡 <i>kecha kartadan svetga 186 400 to'ladim</i>
💼 <i>maosh tushdi 6 mln 450 ming kartaga</i>
🔁 <i>bankomatdan 1 mln yechdim</i>
🤝 <i>Akmalga 500 ming qarz berdim</i>
🧾 Chek rasmini yuboring — har bir qatorini o'qib, jamini tekshiraman
❓ <i>bu oy ovqatga qancha ketdi?</i>

Har bir summani <b>tiyinigacha</b> aniq hisoblayman, xato yozilsa — xabarga javob qilib tuzatasiz.

👉 <b>Birinchi qadam:</b> hozir qo'lingizdagi pullarni yozing, masalan:
<i>naqd pulim 850 ming, kartada 3 200 000, 300 dollar bor</i>"""

HELP = """📖 <b>Qanday ishlatiladi</b>

<b>Yozish</b> — oddiy tilda, lotin yoki kirillda, ovoz bilan ham:
• <i>non 6 ming, taksi 18 ming</i>
• <i>2 kg go'sht 98 mingdan, kartadan</i>
• <i>onamga dori 87 500</i> — kim uchunligini ham tushunaman
• <i>kecha / dushanba kuni ...</i> — sanani o'zim qo'yaman
• <i>Makrodan nasiyaga 340 ming</i> — xarajat + qarz
• <i>200$ ni 2 540 000 ga almashtirdim</i> — valyuta ayirboshlash
• <i>kartamda hozir 2 300 000 bor</i> — qoldiqni tekshirib, farqni to'g'rilayman
• 🧾 chek rasmi, 🎙 ovozli xabar

<b>Qarzlar</b>: <i>Akmalga 300 ming qarz berdim</i>, <i>Akmal 100 ming qaytardi</i>, <i>qo'shniga qarzni berdim</i>
<b>Limit</b>: <i>oziq-ovqatga oyiga 3 mln limit qo'y</i>
<b>Eslatma</b>: <i>har oy 5-sanada internet 120 ming</i>

<b>Savol bering</b>:
• <i>bu oy qancha ketdi?</i>  • <i>o'tgan oyga nisbatan qanday?</i>
• <i>sut oxirgi marta qanchadan edi?</i>  • <i>kim ko'p ishlatdi?</i>

<b>Tuzatish</b>: bot xabariga <u>javob (reply)</u> qilib yozing: <i>15 ming edi</i>, <i>kartadan to'laganman</i>, <i>ikkinchisini o'chir</i>.
<b>Bekor qilish</b>: ↩️ tugmasi yoki <i>oxirgisini o'chir</i>.

<b>Pastdagi tugmalar</b>
📊 Hisobot — davr hisoboti, diagramma, Excel, xulosa
💼 Balans — hamyonlar qoldig'i
📒 Tarix — oxirgi yozuvlar (raqamni bosib ko'rish, tuzatish, o'chirish)
🤝 Qarzlar — kim kimga qarzdor
🎯 Limitlar — oylik limitlar holati
🔔 Oylik to'lovlar — har oy takrorlanadigan to'lovlar
↩️ Oxirgisini bekor qilish
⚙️ Sozlamalar — hamyonlar, kategoriyalar, oila a'zolari, taklif havolasi, kunlik xulosa vaqti

<i>Tugmalar yo'qolib qolsa — klaviatura yonidagi 🎛 belgisini bosing.</i>"""
