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
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fakeredis.aioredis import FakeRedis

from mirage.cache.file.io import mutation_lock
from mirage.cache.file.ram import RAMFileCacheStore
from mirage.cache.index.config import (IndexConfig, IndexEntry, LookupStatus,
                                       RedisIndexConfig)
from mirage.cache.index.ram import RAMIndexCacheStore
from mirage.cache.index.redis import RedisIndexCacheStore
from mirage.cache.index.store import IndexCacheStore
from mirage.cache.index.view import IndexView
from mirage.ops.registry import RegisteredOp
from mirage.vfs.ram import RAMVFS
from mirage.workspace import Workspace


@pytest.mark.asyncio
@pytest.mark.parametrize("store_kind", ["ram", "redis"])
@pytest.mark.parametrize("phase", ["backend", "store"])
@pytest.mark.parametrize("method", [
    "put", "set_dir", "set_partial_dir", "seed_get", "seed_list_dir",
    "seed_entries"
])
@pytest.mark.parametrize("shadow", [False, True])
async def test_late_index_write_cannot_cross_mount_ownership(
        monkeypatch, store_kind, phase, method, shadow):
    config = IndexConfig()
    if store_kind == "redis":
        url = os.environ.get("REDIS_URL")
        if not url:
            pytest.skip("REDIS_URL not set")
        config = RedisIndexConfig(url=url, key_prefix=f"lifecycle:{uuid4()}:")
    vfs = RAMVFS()
    prefix = "/" if shadow else "/data"
    ws = Workspace({prefix: vfs}, index=config)
    ws.add_mount("/alias", vfs)
    index = vfs.index
    entry = IndexEntry(id="old", name="stale", resource_type="file")
    entered = asyncio.Event()
    release = asyncio.Event()

    async def pause():
        entered.set()
        await release.wait()

    if phase == "store":
        store_method = method.removeprefix("seed_")
        original = getattr(index, store_method)

        async def delayed_store(*args, **kwargs):
            await pause()
            return await original(*args, **kwargs)

        monkeypatch.setattr(index, store_method, delayed_store)

    async def delayed_readdir(_accessor, _path, *, index, **_kwargs):
        if phase == "backend":
            await pause()
        if method == "put":
            await index.put("/data/stale", entry)
        elif method == "set_dir":
            await index.set_dir("/data", [("stale", entry)])
        elif method == "set_partial_dir":
            await index.set_partial_dir("/data", [("stale", entry)])
        else:
            index.seed({"/data/stale": entry}, {"/data": ["/data/stale"]},
                       datetime.now(timezone.utc) + timedelta(hours=1))
            if method == "seed_get":
                await index.get("/data/stale")
            elif method == "seed_list_dir":
                await index.list_dir("/data")
            else:
                await index.entries()
        return ["/data/stale"]

    ws.mount(prefix).register_op(
        RegisteredOp(name="readdir",
                     vfs="ram",
                     filetype=None,
                     fn=delayed_readdir))
    reading = asyncio.create_task(ws.vfs.readdir("/data"))
    changing = None
    replacement = RAMVFS()
    replacement.accessor.store.files["/own"] = b"own\n"
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        if shadow:
            ws.add_mount("/data", replacement)
            changing = asyncio.create_task(ws.vfs.readdir("/data"))
        else:
            changing = asyncio.create_task(ws.unmount("/data"))
        await asyncio.sleep(0)
        if phase == "store":
            assert not changing.done()
            release.set()
        await asyncio.wait_for(changing, timeout=5)
        if not shadow:
            ws.add_mount("/data", replacement)
            await ws.vfs.readdir("/data")
        fresh = IndexEntry(id="new", name="fresh", resource_type="file")
        await replacement.index.put("/data/fresh", fresh)
        release.set()
        await asyncio.wait_for(reading, timeout=5)
        for candidate in (index, replacement.index):
            assert (
                await
                candidate.get("/data/stale")).status == LookupStatus.NOT_FOUND
            assert "/data/stale" not in ((await
                                          candidate.list_dir("/data")).entries
                                         or [])
            if method in ("set_dir", "set_partial_dir"):
                listing = await candidate.list_dir("/data")
                shares = (candidate is replacement.index
                          or store_kind == "redis")
                own = ["/data/own"] if shares else None
                assert (listing.entries, listing.partial_entries) == (own,
                                                                      None)
        assert (await replacement.index.get("/data/fresh")).entry.id == "new"
    finally:
        release.set()
        await asyncio.gather(reading,
                             *([changing] if changing else []),
                             return_exceptions=True)
        await index.clear()
        await ws.close()


T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
EPOCH = datetime.fromtimestamp(0, timezone.utc)
YEAR = timedelta(days=365)


class _Clock(datetime):
    at: datetime = T0

    @classmethod
    def now(cls, tz=None):
        return cls.at

    @classmethod
    def advance(cls, seconds: float) -> None:
        cls.at += timedelta(seconds=seconds)


@pytest.fixture
def clock(monkeypatch):
    _Clock.at = T0
    for module in ("view", "ram", "redis"):
        monkeypatch.setattr(f"mirage.cache.index.{module}.datetime", _Clock)
    return _Clock


@asynccontextmanager
async def _store(kind: str, ttl: float) -> AsyncIterator[IndexCacheStore]:
    if kind == "ram":
        yield RAMIndexCacheStore(ttl=ttl)
        return
    url = os.environ.get("REDIS_URL")
    if kind == "redis" and not url:
        pytest.skip("REDIS_URL not set")
    client = FakeRedis() if kind == "fake-redis" else None
    store = RedisIndexCacheStore(ttl=ttl,
                                 client=client,
                                 url=url or "redis://localhost:6379/0",
                                 key_prefix=f"view:[{uuid4()}]:")
    try:
        yield store
    finally:
        await store.clear()
        await store.close()
        if client is not None:
            await client.aclose()


class _SpyStore(RAMIndexCacheStore):

    def __init__(self, ttl: float) -> None:
        super().__init__(ttl=ttl)
        self.asked: list[datetime | None] = []

    async def set_dir(self, vfs_path, entries, expired_at=None) -> None:
        self.asked.append(expired_at)
        await super().set_dir(vfs_path, entries, expired_at)

    async def set_partial_dir(self,
                              vfs_path,
                              entries,
                              expired_at=None) -> None:
        self.asked.append(expired_at)
        await super().set_partial_dir(vfs_path, entries, expired_at)


def _row(name: str = "a") -> IndexEntry:
    return IndexEntry(id=name, name=name, resource_type="file")


def _owns_all(_key: str) -> bool:
    return True


def _owns_none(_key: str) -> bool:
    return False


_FENCED = {
    "get": lambda view: view.get("/data/a"),
    "list_dir": lambda view: view.list_dir("/data"),
    "put": lambda view: view.put("/data/a", _row()),
    "set_dir": lambda view: view.set_dir("/data", [("a", _row())]),
    "set_partial_dir":
    lambda view: view.set_partial_dir("/data", [("a", _row())]),
    "entries": lambda view: view.entries(),
    "invalidate_dir": lambda view: view.invalidate_dir("/data"),
    "invalidate_prefix": lambda view: view.invalidate_prefix("/data"),
    "invalidate": lambda view: view.invalidate(),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("method", list(_FENCED))
async def test_a_locked_view_never_waits_for_the_lock_its_caller_holds(method):
    cache = RAMFileCacheStore()
    store = RAMIndexCacheStore()
    async with mutation_lock(cache):
        view = IndexView(store, cache, "/data", _owns_all, locked=True)
        await asyncio.wait_for(_FENCED[method](view), 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("method", list(_FENCED))
async def test_an_unlocked_view_waits_for_the_mutation_lock(method):
    cache = RAMFileCacheStore()
    view = IndexView(RAMIndexCacheStore(), cache, "/data", _owns_all)
    lock = mutation_lock(cache)
    await lock.acquire()
    call = asyncio.ensure_future(_FENCED[method](view))
    try:
        await asyncio.sleep(0.02)
        assert not call.done()
        lock.release()
        await asyncio.wait_for(call, 1)
    finally:
        if lock.locked():
            lock.release()
        await asyncio.gather(call, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["put", "set_dir", "set_partial_dir"])
@pytest.mark.parametrize("owned", [False, True])
async def test_a_locked_view_keeps_the_ownership_fence(method, owned):
    cache = RAMFileCacheStore()
    store = RAMIndexCacheStore()
    owns = _owns_all if owned else _owns_none
    async with mutation_lock(cache):
        view = IndexView(store, cache, "/data", owns, locked=True)
        await asyncio.wait_for(_FENCED[method](view), 1)
    listing = await store.list_dir("/data")
    written = {
        "put": (await store.get("/data/a")).entry is not None,
        "set_dir": listing.entries == ["/data/a"],
        "set_partial_dir": listing.partial_entries == ["/data/a"],
    }[method]
    assert written is owned
    if not owned:
        assert (await store.get("/data/a")).entry is None
        assert (listing.entries, listing.partial_entries) == (None, None)


# (store ttl, mount read ttl, the writer's expiry, seconds later, status).
# None as the status is a live listing.
CAP_ROWS = [
    (86400, 2, None, 3, LookupStatus.EXPIRED),
    (86400, 2, None, 1, None),
    (60, 600, None, 61, LookupStatus.EXPIRED),
    (60, 600, None, 59, None),
    (0, 600, None, 0, LookupStatus.EXPIRED),
    (86400, 2, "year", 3, LookupStatus.EXPIRED),
    (60, 600, "year", 61, None),
    (86400, 2, "epoch", 0, LookupStatus.EXPIRED),
    (86400, None, None, 3, None),
    (86400, None, "year", 3, None),
]


def _expiry(explicit: str | None) -> datetime | None:
    if explicit is None:
        return None
    return T0 + YEAR if explicit == "year" else EPOCH


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["ram", "fake-redis", "redis"])
@pytest.mark.parametrize("method", ["set_dir", "set_partial_dir"])
@pytest.mark.parametrize("store_ttl,read_ttl,explicit,after,status", CAP_ROWS)
async def test_the_view_caps_a_listing_only_when_it_must(
        clock, kind, method, store_ttl, read_ttl, explicit, after, status):
    async with _store(kind, store_ttl) as store:
        view = IndexView(store,
                         RAMFileCacheStore(),
                         "/data",
                         _owns_all,
                         read_ttl=read_ttl)
        await getattr(view, method)("/data", [("a", _row())],
                                    _expiry(explicit))
        clock.advance(after)
        assert (await store.list_dir("/data")).status == status


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["ram", "fake-redis", "redis"])
@pytest.mark.parametrize("after,status", [(1, None),
                                          (3, LookupStatus.EXPIRED)])
async def test_the_cap_counts_from_the_write_not_the_view(
        clock, kind, after, status):
    async with _store(kind, 86400) as store:
        view = IndexView(store,
                         RAMFileCacheStore(),
                         "/data",
                         _owns_all,
                         read_ttl=2)
        clock.advance(5)
        await view.set_dir("/data", [("a", _row())])
        clock.advance(after)
        assert (await store.list_dir("/data")).status == status


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["set_dir", "set_partial_dir"])
@pytest.mark.parametrize("store_ttl,read_ttl,asked", [
    (60, 600, None),
    (86400, 2, T0 + timedelta(seconds=2)),
])
async def test_the_view_passes_the_writer_expiry_through_unless_it_caps(
        clock, method, store_ttl, read_ttl, asked):
    store = _SpyStore(store_ttl)
    view = IndexView(store,
                     RAMFileCacheStore(),
                     "/data",
                     _owns_all,
                     read_ttl=read_ttl)
    await getattr(view, method)("/data", [("a", _row())])
    assert store.asked == [asked]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["ram", "fake-redis", "redis"])
@pytest.mark.parametrize("explicit,after", [("year", 3), ("epoch", 0)])
async def test_a_seed_is_capped_for_every_folder(clock, kind, explicit, after):
    async with _store(kind, 86400) as store:
        view = IndexView(store,
                         RAMFileCacheStore(),
                         "/data",
                         _owns_all,
                         read_ttl=2)
        folders = ["/data/one", "/data/two", "/data/three"]
        view.seed({folder + "/f": _row("f")
                   for folder in folders},
                  {folder: [folder + "/f"]
                   for folder in folders}, _expiry(explicit))
        clock.advance(after)
        assert [(await store.list_dir(folder)).status
                for folder in folders] == [LookupStatus.EXPIRED] * 3


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["ram", "fake-redis", "redis"])
async def test_the_cap_is_taken_after_the_fence_is_entered(clock, kind):
    async with _store(kind, 86400) as store:
        cache = RAMFileCacheStore()
        view = IndexView(store, cache, "/data", _owns_all, read_ttl=2)
        lock = mutation_lock(cache)
        await lock.acquire()
        writing = asyncio.ensure_future(view.set_dir("/data", [("a", _row())]))
        try:
            await asyncio.sleep(0.02)
            assert not writing.done()
            clock.advance(1.5)
            lock.release()
            await asyncio.wait_for(writing, 1)
            clock.advance(1)
            assert (await store.list_dir("/data")).status is None
            clock.advance(1.1)
            expired = await store.list_dir("/data")
            assert expired.status == LookupStatus.EXPIRED
        finally:
            if lock.locked():
                lock.release()
            await asyncio.gather(writing, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["ram", "fake-redis", "redis"])
async def test_a_view_reports_the_lifetime_its_listings_get(kind):
    # Uncapped, the store's default; capped, whichever is shorter, since
    # that is how long a listing written through the view lives.
    async with _store(kind, 42) as store:
        cache = RAMFileCacheStore()
        assert IndexView(store, cache, "/data", _owns_all).ttl == 42
        assert IndexView(store, cache, "/data", _owns_all,
                         read_ttl=10).ttl == 10
        assert IndexView(store, cache, "/data", _owns_all,
                         read_ttl=600).ttl == 42
        await store.clear()
        await store.close()
