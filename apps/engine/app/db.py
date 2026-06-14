"""PostgreSQL connection pool (asyncpg).

The engine writes to the same database Prisma manages from the NestJS API —
it only ever touches the `Candle` table, matching the schema defined there.
"""

import asyncpg

from app.config import Settings


class Database:
    def __init__(self, settings: Settings):
        self._dsn = settings.database_url
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        if not self._dsn:
            return
        self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=5)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    @property
    def pool(self) -> asyncpg.Pool | None:
        return self._pool

    @property
    def is_connected(self) -> bool:
        return self._pool is not None
