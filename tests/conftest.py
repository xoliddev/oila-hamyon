import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hamyon.core import dates  # noqa: E402
from hamyon.db.database import Database  # noqa: E402
from hamyon.services import family as fam  # noqa: E402


@pytest.fixture
async def db():
    database = Database(":memory:")
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
async def household(db):
    """Oila: Aziz (admin), Malika (Ona), Bobur. USD kursi oldindan yozilgan (tarmoqsiz)."""
    fid = await fam.create_family(db, "Test")
    r = await fam.add_member(db, fid, 1, "Aziz", "Katta o'g'il", True)
    d = await fam.add_member(db, fid, 2, "Malika", "Ona", False)
    s = await fam.add_member(db, fid, 3, "Bobur", "Kichik o'g'il", False)
    today = dates.today()
    from datetime import timedelta
    for i in range(0, 40):
        day = (today - timedelta(days=i)).isoformat()
        await db.execute("INSERT INTO fx_rates (currency, date, rate) VALUES ('USD', ?, '12000')", (day,))
        await db.execute("INSERT INTO fx_rates (currency, date, rate) VALUES ('EUR', ?, '13000')", (day,))
    wallets = {w["name"]: w for w in await fam.wallets(db, fid)}
    return {
        "family_id": fid,
        "rustam": await fam.get_member(db, r),
        "ona": await fam.get_member(db, d),
        "sardor": await fam.get_member(db, s),
        "wallets": wallets,
    }
