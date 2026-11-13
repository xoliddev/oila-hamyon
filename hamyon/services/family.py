"""Oila, a'zolar, hamyonlar va kategoriyalar."""
from __future__ import annotations

import difflib
import secrets

from hamyon.core.text import normalize_name
from hamyon.db.database import Database

# (key, nom, emoji, AI uchun misollar)
DEFAULT_EXPENSE_CATEGORIES = [
    ("oziq_ovqat", "Oziq-ovqat", "🛒", "non, go'sht, tovuq, sut, qatiq, tuxum, guruch, un, yog', shakar, choy, sabzavot, meva, bozor, supermarket, korzinka, makro, havas, do'kon mahsulotlari, suv (ichimlik), shirinlik, non-pishiriq"),
    ("kafe", "Kafe va tashqarida ovqat", "🍽", "kafe, restoran, choyxona, fastfud, lavash, shaurma, burger, pitsa, somsa (ko'chada), osh (oshxonada), kofe, dostavka, yetkazib berish, wolt, yandex eda, tushlik (ishda)"),
    ("kommunal", "Kommunal to'lovlar", "💡", "svet, elektr, gaz, suv (kommunal), issiqlik, otopleniye, chiqindi, musor, kvartplata, uy-joy xizmati, TSJ, domofon, lift"),
    ("aloqa", "Aloqa va internet", "📱", "telefon balansi, mobil aloqa, beeline, ucell, mobiuz, uzmobile, internet, uzonline, TV, IPTV, paynet"),
    ("transport", "Transport", "🚕", "taksi, yandex go, mytaxi, avtobus, metro, marshrutka, poyezd, samolyot bileti, avia bilet"),
    ("avto", "Avtomobil", "⛽", "benzin, metan, propan, zapravka, moy almashtirish, ehtiyot qism, remont, moyka, avtoturargoh, parkovka, jarima, shtraf, sug'urta, texosmotr"),
    ("uy", "Uy-ro'zg'or", "🏠", "kir yuvish kukuni, sovun, shampun, gigiyena, tozalash vositalari, idish-tovoq, maishiy texnika, mebel, uy ta'miri, santexnika, lampochka, gilam"),
    ("kiyim", "Kiyim-kechak", "👕", "kiyim, poyabzal, oyoq kiyim, kurtka, ko'ylak, shim, sumka, tikuvchi, kimyoviy tozalash"),
    ("salomatlik", "Salomatlik", "💊", "dori, apteka, dorixona, shifokor, klinika, analiz, UZI, stomatolog, tish, ko'zoynak, vitamin, massaj"),
    ("talim", "Ta'lim", "📚", "kontrakt, o'qish, kurs, repetitor, kitob, daftar, ruchka, maktab, universitet, test markaz, sertifikat imtihoni"),
    ("shaxsiy", "Shaxsiy parvarish", "💇", "sartarosh, soch oldirish, salon, kosmetika, atir, manikyur"),
    ("marosim", "To'y va marosimlar", "🎉", "to'y, to'yona, ma'raka, osh berish, nikoh, tug'ilgan kun ziyofati, beshik to'y, sunnat to'y, aza, xudoyi"),
    ("sovga", "Sovg'alar", "🎁", "sovg'a, hadya, gul, tug'ilgan kun sovg'asi, bayram sovg'asi, bolalarga pul berish (oila tashqarisi)"),
    ("xayriya", "Xayriya va sadaqa", "🤲", "sadaqa, ehson, zakot, fitr, xayriya, masjidga, yordam"),
    ("dam_olish", "Dam olish va ko'ngilochar", "🎮", "kino, park, sayohat, mehmonxona, dam olish maskani, obuna, netflix, youtube premium, telegram premium, o'yin, sport zal, futbol"),
    ("kredit", "Kredit va bo'lib to'lash", "🏦", "bank krediti oylik to'lovi, mikroqarz, rassrochka, muddatli to'lov, ipoteka to'lovi"),
    ("tolov", "Soliq, komissiya, rasmiy to'lovlar", "🧾", "soliq, mol-mulk solig'i, davlat boji, notarius, bank komissiyasi, o'tkazma komissiyasi, jarima (avtodan tashqari), hujjat"),
    ("boshqa_chiqim", "Boshqa chiqimlar", "📦", "boshqa hech biriga to'g'ri kelmaydigan chiqim"),
]

DEFAULT_INCOME_CATEGORIES = [
    ("maosh", "Maosh", "💼", "oylik, maosh, zarplata, avans, premiya, bonus"),
    ("biznes", "Biznes va qo'shimcha daromad", "💰", "savdo, do'kon foydasi, frilans, buyurtma, xizmat haqi, ish haqi (bir martalik), taksi daromadi"),
    ("pensiya", "Pensiya va nafaqa", "🧓", "pensiya, nafaqa, stipendiya, ijtimoiy to'lov"),
    ("ijara_kirim", "Ijara daromadi", "🏘", "kvartira ijarasi, uy ijarasi, do'kon ijarasi tushumi"),
    ("sovga_kirim", "Sovg'a / hadya olindi", "🎁", "sovg'a qilishdi, to'yona tushdi, qarindosh berdi (qaytarilmaydi), xorijdan pul jo'natishdi (sovg'a)"),
    ("foiz", "Foiz va keshbek", "📈", "depozit foizi, keshbek, bonus ball naqdlashtirildi"),
    ("boshqa_kirim", "Boshqa kirim", "➕", "boshqa hech biriga to'g'ri kelmaydigan kirim, sotilgan buyum"),
]

DEFAULT_WALLETS = [
    ("Naqd", "cash", "UZS", 1),
    ("Karta", "card", "UZS", 0),
    ("Dollar", "cash", "USD", 0),
]

ROLES = ["Ota", "Ona", "Katta o'g'il", "Kichik o'g'il", "O'g'il", "Qiz", "Buvi", "Bobo"]

WALLET_KINDS = {"cash": "💵 Naqd", "card": "💳 Karta", "bank": "🏦 Bank hisobi", "savings": "🐷 Jamg'arma", "other": "👛 Boshqa"}


def new_invite_code() -> str:
    return secrets.token_urlsafe(9).replace("-", "a").replace("_", "b")


async def create_family(db: Database, name: str = "Oila") -> int:
    async with db.transaction() as tx:
        family_id = await tx.execute(
            "INSERT INTO families (name, invite_code) VALUES (?, ?)", (name, new_invite_code())
        )
        for i, (key, title, emoji, hints) in enumerate(DEFAULT_EXPENSE_CATEGORIES):
            await tx.execute(
                "INSERT INTO categories (family_id, key, name, emoji, kind, hints, sort) VALUES (?,?,?,?,?,?,?)",
                (family_id, key, title, emoji, "expense", hints, i),
            )
        for i, (key, title, emoji, hints) in enumerate(DEFAULT_INCOME_CATEGORIES):
            await tx.execute(
                "INSERT INTO categories (family_id, key, name, emoji, kind, hints, sort) VALUES (?,?,?,?,?,?,?)",
                (family_id, key, title, emoji, "income", hints, i),
            )
        for name_, kind, currency, is_default in DEFAULT_WALLETS:
            await tx.execute(
                "INSERT INTO wallets (family_id, name, kind, currency, is_default) VALUES (?,?,?,?,?)",
                (family_id, name_, kind, currency, is_default),
            )
    return family_id


async def family_count(db: Database) -> int:
    return await db.scalar("SELECT COUNT(*) FROM families", default=0)


async def get_family(db: Database, family_id: int) -> dict | None:
    return await db.fetchone("SELECT * FROM families WHERE id=?", (family_id,))


async def all_families(db: Database) -> list[dict]:
    return await db.fetchall("SELECT * FROM families ORDER BY id")


async def family_by_invite(db: Database, code: str) -> dict | None:
    if not code:
        return None
    return await db.fetchone("SELECT * FROM families WHERE invite_code=?", (code.strip(),))


async def regenerate_invite(db: Database, family_id: int) -> str:
    code = new_invite_code()
    await db.execute("UPDATE families SET invite_code=? WHERE id=?", (code, family_id))
    return code


async def update_family(db: Database, family_id: int, **fields) -> None:
    allowed = {"name", "daily_report", "daily_report_time", "monthly_report", "notify_members"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return
    cols = ", ".join(f"{k}=?" for k in sets)
    await db.execute(f"UPDATE families SET {cols} WHERE id=?", (*sets.values(), family_id))


# ---------- a'zolar ----------

async def member_by_tg(db: Database, tg_id: int) -> dict | None:
    return await db.fetchone("SELECT * FROM members WHERE tg_id=? AND is_active=1", (tg_id,))


async def member_by_tg_any(db: Database, tg_id: int) -> dict | None:
    return await db.fetchone("SELECT * FROM members WHERE tg_id=?", (tg_id,))


async def get_member(db: Database, member_id: int) -> dict | None:
    return await db.fetchone("SELECT * FROM members WHERE id=?", (member_id,))


async def add_member(db: Database, family_id: int, tg_id: int, name: str, role: str, is_admin: bool) -> int:
    existing = await member_by_tg_any(db, tg_id)
    if existing:
        await db.execute(
            "UPDATE members SET family_id=?, name=?, role=?, is_admin=?, is_active=1 WHERE id=?",
            (family_id, name, role, int(is_admin), existing["id"]),
        )
        return existing["id"]
    return await db.execute(
        "INSERT INTO members (family_id, tg_id, name, role, is_admin) VALUES (?,?,?,?,?)",
        (family_id, tg_id, name, role, int(is_admin)),
    )


async def members(db: Database, family_id: int, active_only: bool = True) -> list[dict]:
    sql = "SELECT * FROM members WHERE family_id=?" + (" AND is_active=1" if active_only else "") + " ORDER BY id"
    return await db.fetchall(sql, (family_id,))


async def set_member_active(db: Database, member_id: int, active: bool) -> None:
    await db.execute("UPDATE members SET is_active=? WHERE id=?", (int(active), member_id))


async def update_member(db: Database, member_id: int, **fields) -> None:
    allowed = {"name", "role", "default_wallet_id", "is_admin"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if sets:
        cols = ", ".join(f"{k}=?" for k in sets)
        await db.execute(f"UPDATE members SET {cols} WHERE id=?", (*sets.values(), member_id))


def member_label(m: dict | None) -> str:
    if not m:
        return "—"
    return m["name"]


def match_by_name(items: list[dict], name: str | None, *fields: str) -> dict | None:
    """Ism bo'yicha moslash: aniq -> boshlanishi -> o'xshashlik."""
    target = normalize_name(name)
    if not target:
        return None
    fields = fields or ("name",)
    keyed = [(normalize_name(it.get(f)), it) for it in items for f in fields if it.get(f)]
    for key, it in keyed:
        if key == target:
            return it
    for key, it in keyed:
        if key.startswith(target) or target.startswith(key) or target in key.split():
            return it
    names = [k for k, _ in keyed]
    close = difflib.get_close_matches(target, names, n=1, cutoff=0.75)
    if close:
        return next(it for k, it in keyed if k == close[0])
    return None


# ---------- hamyonlar ----------

async def wallets(db: Database, family_id: int, include_archived: bool = False) -> list[dict]:
    sql = "SELECT * FROM wallets WHERE family_id=?" + ("" if include_archived else " AND is_archived=0")
    return await db.fetchall(sql + " ORDER BY is_default DESC, id", (family_id,))


async def get_wallet(db: Database, wallet_id: int) -> dict | None:
    return await db.fetchone("SELECT * FROM wallets WHERE id=?", (wallet_id,))


async def default_wallet(db: Database, family_id: int, member: dict | None = None) -> dict | None:
    if member and member.get("default_wallet_id"):
        w = await db.fetchone(
            "SELECT * FROM wallets WHERE id=? AND is_archived=0", (member["default_wallet_id"],)
        )
        if w:
            return w
    w = await db.fetchone(
        "SELECT * FROM wallets WHERE family_id=? AND is_default=1 AND is_archived=0", (family_id,)
    )
    if w:
        return w
    return await db.fetchone("SELECT * FROM wallets WHERE family_id=? AND is_archived=0 ORDER BY id", (family_id,))


async def add_wallet(db: Database, family_id: int, name: str, kind: str, currency: str) -> int:
    return await db.execute(
        "INSERT INTO wallets (family_id, name, kind, currency) VALUES (?,?,?,?)",
        (family_id, name.strip()[:40], kind, currency),
    )


async def set_default_wallet(db: Database, family_id: int, wallet_id: int) -> None:
    async with db.transaction() as tx:
        await tx.execute("UPDATE wallets SET is_default=0 WHERE family_id=?", (family_id,))
        await tx.execute("UPDATE wallets SET is_default=1 WHERE id=? AND family_id=?", (wallet_id, family_id))


async def archive_wallet(db: Database, family_id: int, wallet_id: int) -> None:
    await db.execute(
        "UPDATE wallets SET is_archived=1, is_default=0 WHERE id=? AND family_id=?", (wallet_id, family_id)
    )


# ---------- kategoriyalar ----------

async def categories(db: Database, family_id: int, kind: str | None = None) -> list[dict]:
    sql = "SELECT * FROM categories WHERE family_id=? AND is_archived=0"
    params: list = [family_id]
    if kind:
        sql += " AND kind=?"
        params.append(kind)
    return await db.fetchall(sql + " ORDER BY kind, sort, id", params)


async def category_by_key(db: Database, family_id: int, key: str | None) -> dict | None:
    if not key:
        return None
    return await db.fetchone(
        "SELECT * FROM categories WHERE family_id=? AND key=? AND is_archived=0", (family_id, key.strip())
    )


async def add_category(db: Database, family_id: int, name: str, emoji: str, kind: str, hints: str = "") -> int:
    base = normalize_name(name).replace(" ", "_")[:24] or "kat"
    key, n = base, 2
    while await category_by_key(db, family_id, key) or await db.fetchone(
        "SELECT 1 FROM categories WHERE family_id=? AND key=?", (family_id, key)
    ):
        key = f"{base}_{n}"
        n += 1
    return await db.execute(
        "INSERT INTO categories (family_id, key, name, emoji, kind, hints, sort) VALUES (?,?,?,?,?,?,500)",
        (family_id, key, name.strip()[:40], emoji or "•", kind, hints),
    )


async def archive_category(db: Database, family_id: int, category_id: int) -> None:
    await db.execute(
        "UPDATE categories SET is_archived=1 WHERE id=? AND family_id=? AND key NOT IN ('boshqa_chiqim','boshqa_kirim')",
        (category_id, family_id),
    )
