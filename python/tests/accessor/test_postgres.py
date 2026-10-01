# ========= Copyright 2026 @ Strukto.AI All Rights Reserved. =========
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ========= Copyright 2026 @ Strukto.AI All Rights Reserved. =========

import asyncio
from unittest.mock import AsyncMock

import pytest

from mirage.accessor.postgres import PostgresAccessor
from mirage.vfs.postgres.config import PostgresConfig


@pytest.mark.asyncio
async def test_concurrent_initialization_and_close(monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()
    pool = AsyncMock()

    async def connect(*args, **kwargs):
        entered.set()
        await release.wait()
        return pool

    factory = AsyncMock(side_effect=connect)
    monkeypatch.setattr(
        "mirage.accessor.postgres.asyncpg.create_pool", factory
    )
    accessor = PostgresAccessor(PostgresConfig(dsn="postgresql://unused"))
    first = asyncio.create_task(accessor.pool())
    await entered.wait()
    second = asyncio.create_task(accessor.pool())
    release.set()
    assert await first is await second is pool
    await asyncio.gather(accessor.close(), accessor.close())
    factory.assert_awaited_once()
    pool.close.assert_awaited_once()
