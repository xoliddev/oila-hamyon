"""Konsol simulyatori: Telegram'siz botning "miyasini" sinash.

Ishlatish:
    python tools/simulate.py                      # interaktiv
    python tools/simulate.py "non 6 ming" "taksi 18 ming"   # ketma-ket xabarlar
    python tools/simulate.py --db data/sim.db --as Ona "sutga 12 ming"

Maxsus buyruqlar: /balans, /hisobot, /qarzlar, /byudjet, /bekor, /tuzat <matn>, /ha (tasdiqlash), /exit
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hamyon.ai.client import AIClient  # noqa: E402
from hamyon.core import dates  # noqa: E402
from hamyon.db.database import Database  # noqa: E402
from hamyon.services import budgets, family as fam, ledger, reports  # noqa: E402
from hamyon.services.engine import Engine  # noqa: E402


def plain(html: str) -> str:
    return re.sub(r"</?[a-z]+>", "", html).replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


async def ensure_family(db: Database) -> dict[str, dict]:
    if not await fam.family_count(db):
        fid = await fam.create_family(db, "Sinov oilasi")
        await fam.add_member(db, fid, 1001, "Aziz", "Katta o'g'il", True)
        await fam.add_member(db, fid, 1002, "Malika", "Ona", False)
        await fam.add_member(db, fid, 1003, "Bobur", "Kichik o'g'il", False)
    ms = await fam.members(db, 1)
    return {m["name"].lower(): m for m in ms} | {m["role"].lower(): m for m in ms}


async def run_one(engine: Engine, db: Database, member: dict, text: str, state: dict) -> None:
    fid = member["family_id"]
    if text == "/balans":
        print(plain((await reports.wallets_text(db, fid))[0]))
        return
    if text == "/hisobot":
        s, e = dates.period_bounds("month")
        print(plain(await reports.period_report_text(db, fid, s, e, "Shu oy")))
        return
    if text == "/qarzlar":
        for d in await ledger.open_debts(db, fid):
            print(d["direction"], d["counterparty"], d["remaining"] / 100, d["currency"])
        return
    if text == "/byudjet":
        for b in await budgets.budget_status(db, fid):
            print(plain(budgets.render_budget_line(b)))
        return
    if text == "/ha" and state.get("pending"):
        r = await engine.confirm_pending(member, state.pop("pending"))
        print(plain(r.text))
        state["last"] = r
        return
    if text.startswith("/tuzat ") and state.get("last"):
        last = state["last"]
        link = {"batch_id": last.batch_id, "tx_id_list": last.tx_ids, "pending_id": last.pending_id}
        replies = await engine.correct(member, link, text[7:])
    else:
        replies = await engine.handle(member, text=text)
    for r in replies:
        print(f"[{r.kind}]")
        print(plain(r.text))
        print()
        if r.kind == "confirm":
            state["pending"] = r.pending_id
        if r.kind in ("saved", "confirm"):
            state["last"] = r


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/simulate.db")
    ap.add_argument("--as", dest="who", default="rustam")
    ap.add_argument("messages", nargs="*")
    args = ap.parse_args()
    db = Database(args.db)
    await db.connect()
    people = await ensure_family(db)
    member = people.get(args.who.lower()) or next(iter(people.values()))
    engine = Engine(db, AIClient(db))
    state: dict = {}
    try:
        if args.messages:
            for msg in args.messages:
                print(f">>> {member['name']}: {msg}")
                await run_one(engine, db, member, msg, state)
                print("-" * 50)
        else:
            while True:
                msg = input(f"{member['name']}> ").strip()
                if msg in ("/exit", "exit", "q"):
                    break
                if msg:
                    await run_one(engine, db, member, msg, state)
    finally:
        await db.close()


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
