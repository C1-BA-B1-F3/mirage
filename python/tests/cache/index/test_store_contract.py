import asyncio
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis

from mirage.cache.index import IndexEntry, LookupStatus, RAMIndexCacheStore
from mirage.cache.index.redis import RedisIndexCacheStore


@pytest_asyncio.fixture(params=["ram", "fake-redis", "redis"])
async def store_factory(request):
    backend = request.param
    url = os.environ.get("REDIS_URL")
    if backend == "redis" and not url:
        pytest.skip("REDIS_URL not set")
    client = FakeRedis() if backend == "fake-redis" else None
    prefix = f"contract:[{uuid4()}]:"
    stores = []

    def build():
        if backend == "ram":
            if stores:
                return stores[0]
            value = RAMIndexCacheStore(ttl=1)
        else:
            value = RedisIndexCacheStore(ttl=1,
                                         client=client,
                                         url=url or "redis://localhost:6379/0",
                                         key_prefix=prefix)
        stores.append(value)
        return value

    yield build
    cleanup = build()
    await cleanup.clear()
    for value in stores:
        await value.close()
    if client is not None:
        await client.aclose()


@pytest.fixture
def store(store_factory):
    return store_factory()


def entry(name="a"):
    return IndexEntry(id=name,
                      name=name,
                      resource_type="file",
                      size=2,
                      remote_time="2026-09-05T10:55:39.123000Z",
                      extra={"nested": {
                          "tags": ["x", "y"]
                      }})


@pytest.mark.asyncio
async def test_listing_lifecycle(store):
    assert (await store.list_dir("/dir")).status == LookupStatus.NOT_FOUND
    await store.set_dir("/dir", [])
    assert (await store.list_dir("/dir")).entries == []
    await store.set_dir("/dir", [("b", entry("b")), ("a", entry())])
    assert (await store.list_dir("/dir")).entries == ["/dir/b", "/dir/a"]
    got = (await store.get("/dir/a")).entry
    assert got.model_dump(exclude={"index_time"}) == entry().model_dump(
        exclude={"index_time"})
    assert got.index_time
    await asyncio.sleep(1.1)
    assert (await store.list_dir("/dir")).status == LookupStatus.EXPIRED
    assert (await store.get("/dir/a")).entry == got
    await store.invalidate_dir("/dir")
    assert (await store.list_dir("/dir")).status == LookupStatus.NOT_FOUND
    assert (await store.get("/dir/a")).status == LookupStatus.NOT_FOUND


@pytest.mark.asyncio
@pytest.mark.parametrize("offset", [-1, 0])
async def test_past_deadline_is_not_clamped(store, offset):
    deadline = datetime.now(timezone.utc) + timedelta(seconds=offset)
    await store.set_dir("/dir", [("a", entry())], deadline)
    assert (await store.list_dir("/dir")).status == LookupStatus.EXPIRED


@pytest.mark.asyncio
async def test_invalidate_preserves_stale_distinction_and_can_refill(store):
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    store.seed({"/dir/a": entry()}, {"/dir": ["/dir/a"], "/empty": []}, future)
    await store.invalidate()
    assert (await store.list_dir("/dir")).status == LookupStatus.EXPIRED
    assert (await store.list_dir("/empty")).status == LookupStatus.EXPIRED
    assert (await store.list_dir("/absent")).status == LookupStatus.NOT_FOUND
    assert (await store.get("/dir/a")).entry is not None
    await store.set_dir("/dir", [], future)
    assert (await store.list_dir("/dir")).entries == []
    assert (await store.list_dir("/empty")).status == LookupStatus.EXPIRED


@pytest.mark.asyncio
async def test_seeds_merge_copy_inputs_and_flush_on_close(
        store, store_factory):
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    children = {"/one": ["/one/a"]}
    store.seed({"/one/a": entry()}, children, future)
    children["/one"].clear()
    store.seed({"/two/b": entry("b")}, {
        "/two": ["/two/b"],
        "/empty": []
    }, future)
    await store.close()
    await store.close()
    reader = store_factory()
    assert (await reader.list_dir("/one")).entries == ["/one/a"]
    assert (await reader.list_dir("/two")).entries == ["/two/b"]
    assert (await reader.list_dir("/empty")).entries == []
    assert set(await reader.entries()) == {"/one/a", "/two/b"}


@pytest.mark.asyncio
async def test_clear_discards_pending_seeds(store):
    store.seed({"/a": entry()}, {"/": ["/a"]}, datetime.now(timezone.utc))
    await store.clear()
    assert await store.entries() == {}
    assert (await store.list_dir("/")).status == LookupStatus.NOT_FOUND


@pytest.mark.asyncio
async def test_prefix_invalidation_is_literal_and_scoped(store):
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    for path in ["/a[1]", "/a[1]/nested", "/a1", "/a[1]-other"]:
        await store.set_dir(path, [("a", entry())], future)
    await store.invalidate_prefix("/a[1]")
    for path in ["/a[1]", "/a[1]/nested"]:
        assert (await store.list_dir(path)).status == LookupStatus.NOT_FOUND
        assert (await store.get(path + "/a")).status == LookupStatus.NOT_FOUND
    for path in ["/a1", "/a[1]-other"]:
        assert (await store.list_dir(path)).entries == [path + "/a"]


@pytest.mark.asyncio
async def test_invalidation_is_visible_to_other_clients(store, store_factory):
    peer = store_factory()
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    await store.set_dir("/dir", [("a", entry())], future)
    await peer.invalidate()
    assert (await store.list_dir("/dir")).status == LookupStatus.EXPIRED
    await store.set_dir("/dir", [], future)
    assert (await peer.list_dir("/dir")).entries == []
    await peer.invalidate_dir("/dir")
    await store.invalidate()
    assert (await peer.list_dir("/dir")).status == LookupStatus.NOT_FOUND


@pytest.mark.asyncio
async def test_ttl_is_the_configured_listing_lifetime(store):
    assert store.ttl == 1
