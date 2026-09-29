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

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from mirage.accessor.postgres import PostgresAccessor
from mirage.cache.index.ram import RAMIndexCacheStore
from mirage.commands.builtin.postgres.wc import wc
from mirage.commands.config import CommandOpts
from mirage.io.stream import materialize
from mirage.types import PathSpec
from mirage.vfs.postgres.config import PostgresConfig


@asynccontextmanager
async def _fake_acquire():
    yield MagicMock()


def _accessor(**config) -> PostgresAccessor:
    a = PostgresAccessor(
        PostgresConfig(dsn="postgres://localhost/db", **config))
    pool = MagicMock()
    pool.acquire = lambda: _fake_acquire()
    a.pool = AsyncMock(return_value=pool)
    return a


async def _catalog_schemas(conn, allowlist):
    return [
        s for s in ("public", "secret") if allowlist is None or s in allowlist
    ]


@pytest.fixture
def catalog(monkeypatch):
    monkeypatch.setattr("mirage.core.postgres.client.list_schemas",
                        AsyncMock(side_effect=_catalog_schemas))
    monkeypatch.setattr("mirage.core.postgres.client.list_tables",
                        AsyncMock(return_value=["users"]))


def _path(s: str) -> PathSpec:
    return PathSpec(virtual=s, directory=s, vfs_path=s.strip("/"))


@pytest.mark.asyncio
async def test_wc_l_counts_a_visible_table_server_side(monkeypatch, catalog):
    monkeypatch.setattr("mirage.core.postgres.client.count_rows",
                        AsyncMock(return_value=42))
    out, io = await wc(
        _accessor(), [_path("/public/tables/users/rows.jsonl")], [],
        CommandOpts(index=RAMIndexCacheStore(), flags={"lines": True}))
    assert await materialize(out) == b"42 /public/tables/users/rows.jsonl\n"
    assert io.exit_code == 0


@pytest.mark.asyncio
async def test_wc_l_refuses_a_table_outside_schemas(monkeypatch, catalog):
    """``wc -l`` counted the relation by the names in the path, so a
    table under a schema ``schemas`` leaves out printed its row count."""
    count = AsyncMock(side_effect=AssertionError("counted the relation"))
    monkeypatch.setattr("mirage.core.postgres.client.count_rows", count)
    out, io = await wc(
        _accessor(schemas=["public"]),
        [_path("/secret/tables/users/rows.jsonl")], [],
        CommandOpts(index=RAMIndexCacheStore(), flags={"lines": True}))
    await materialize(out)
    assert io.exit_code == 1
    assert b"No such file or directory" in await materialize(io.stderr)
    count.assert_not_awaited()
