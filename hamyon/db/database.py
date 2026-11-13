"""Yupqa aiosqlite o'rami: bitta ulanish, WAL rejimi, dict qatorlar, tranzaksiya qulfi."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Iterable

import aiosqlite

log = logging.getLogger(__name__)
SCHEMA = Path(__file__).with_name("schema.sql")


class Database:
    def __init__(self, path: Path | str):
        self.path = str(path)
        self.conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA journal_mode=WAL")
        await self.conn.execute("PRAGMA foreign_keys=ON")
        await self.conn.execute("PRAGMA busy_timeout=5000")
        await self.conn.executescript(SCHEMA.read_text(encoding="utf-8"))
        await self.conn.commit()
        log.info("DB tayyor: %s", self.path)

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()
            self.conn = None

    async def fetchone(self, sql: str, params: Iterable[Any] = ()) -> dict | None:
        async with self.conn.execute(sql, tuple(params)) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def fetchall(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        async with self.conn.execute(sql, tuple(params)) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def scalar(self, sql: str, params: Iterable[Any] = (), default: Any = None) -> Any:
        async with self.conn.execute(sql, tuple(params)) as cur:
            row = await cur.fetchone()
        if row is None or row[0] is None:
            return default
        return row[0]

    async def execute(self, sql: str, params: Iterable[Any] = ()) -> int:
        """Bitta buyruq + commit. lastrowid qaytaradi."""
        async with self._lock:
            cur = await self.conn.execute(sql, tuple(params))
            await self.conn.commit()
            return cur.lastrowid

    async def execute_rowcount(self, sql: str, params: Iterable[Any] = ()) -> int:
        """Bitta buyruq + commit. O'zgargan qatorlar sonini qaytaradi (atomar "egallash" uchun)."""
        async with self._lock:
            cur = await self.conn.execute(sql, tuple(params))
            await self.conn.commit()
            return cur.rowcount

    async def execute_returning(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        """DELETE/UPDATE ... RETURNING - qatorni bir martagina olish (ikki marta bosishdan himoya)."""
        async with self._lock:
            async with self.conn.execute(sql, tuple(params)) as cur:
                rows = [dict(r) for r in await cur.fetchall()]
            await self.conn.commit()
            return rows

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator["Tx"]:
        """Bir nechta yozuvni atomar saqlash: hammasi yoki hech biri."""
        async with self._lock:
            await self.conn.execute("BEGIN")
            try:
                yield Tx(self.conn)
            except BaseException:
                await self.conn.rollback()
                raise
            else:
                await self.conn.commit()

    async def backup_to(self, target: Path) -> None:
        async with self._lock:
            dest = await aiosqlite.connect(str(target))
            try:
                await self.conn.backup(dest)
            finally:
                await dest.close()


class Tx:
    """Tranzaksiya ichidagi ulanish (commit qilmaydi)."""

    def __init__(self, conn: aiosqlite.Connection):
        self.conn = conn

    async def execute(self, sql: str, params: Iterable[Any] = ()) -> int:
        cur = await self.conn.execute(sql, tuple(params))
        return cur.lastrowid

    async def fetchone(self, sql: str, params: Iterable[Any] = ()) -> dict | None:
        async with self.conn.execute(sql, tuple(params)) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def fetchall(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        async with self.conn.execute(sql, tuple(params)) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]
