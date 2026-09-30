import asyncio
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis

from mirage.cache.index import (Evicted, IndexEntry, LookupStatus,
                                RAMIndexCacheStore)
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


def folder(name):
    return IndexEntry(id=name, name=name, resource_type="folder")


@pytest.mark.asyncio
async def test_first_listing_evicts_nothing(store):
    assert await store.set_dir("/dir", [("a", entry())]) == []


@pytest.mark.asyncio
async def test_relist_evicts_the_rows_it_no_longer_names(store):
    await store.set_dir("/dir", [("a", entry()), ("b", entry("b"))])
    assert await store.set_dir(
        "/dir", [("b", entry("b"))]) == [Evicted("/dir/a", folder=False)]
    assert (await store.get("/dir/a")).status == LookupStatus.NOT_FOUND
    assert (await store.get("/dir/b")).entry is not None
    assert (await store.list_dir("/dir")).entries == ["/dir/b"]


@pytest.mark.asyncio
async def test_relist_over_an_expired_listing_still_evicts(store):
    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    await store.set_dir("/dir", [("a", entry()), ("b", entry("b"))], past)
    assert (await store.list_dir("/dir")).status == LookupStatus.EXPIRED
    assert await store.set_dir(
        "/dir", [("b", entry("b"))]) == [Evicted("/dir/a", folder=False)]
    assert (await store.get("/dir/a")).status == LookupStatus.NOT_FOUND


@pytest.mark.asyncio
async def test_a_dropped_folder_takes_its_subtree(store):
    await store.set_dir("/dir", [("sub", folder("sub")), ("f", entry("f"))])
    await store.set_dir("/dir/sub", [("x", entry("x")),
                                     ("deep", folder("deep"))])
    await store.set_dir("/dir/sub/deep", [("y", entry("y"))])
    await store.set_dir("/dir/sub2", [("z", entry("z"))])
    assert await store.set_dir(
        "/dir", [("f", entry("f"))]) == [Evicted("/dir/sub", folder=True)]
    for path in ["/dir/sub", "/dir/sub/x", "/dir/sub/deep/y"]:
        assert (await store.get(path)).status == LookupStatus.NOT_FOUND
    for path in ["/dir/sub", "/dir/sub/deep"]:
        assert (await store.list_dir(path)).status == LookupStatus.NOT_FOUND
    assert (await store.list_dir("/dir/sub2")).entries == ["/dir/sub2/z"]
    assert (await store.get("/dir/sub2/z")).entry is not None


@pytest.mark.asyncio
async def test_partial_listing_evicts_nothing(store):
    await store.set_dir("/dir", [("a", entry()), ("b", entry("b"))])
    await store.set_partial_dir("/dir", [("b", entry("b"))])
    assert (await store.get("/dir/a")).entry is not None


@pytest.mark.asyncio
async def test_relist_keeps_rows_only_put_wrote(store):
    await store.put("/dir/p", entry("p"))
    await store.set_dir("/dir", [("a", entry())])
    assert await store.set_dir("/dir", []) == [Evicted("/dir/a", folder=False)]
    assert (await store.get("/dir/p")).entry is not None


@pytest.mark.asyncio
async def test_a_window_listing_evicts_nothing(store):
    # A window names what to show, not every child: dropping out of it is
    # not deletion, so the row stays while the listing is served whole.
    await store.set_dir("/dir", [("a", entry()), ("b", entry("b"))])
    assert await store.set_dir("/dir", [("b", entry("b"))], window=True) == []
    assert (await store.get("/dir/a")).entry is not None
    assert (await store.list_dir("/dir")).entries == ["/dir/b"]


@pytest.mark.asyncio
async def test_a_full_relist_over_a_partial_diffs_only_what_it_named(store):
    # The partial listing never claimed "a", so a later full listing has no
    # evidence that "a" went away; only "b", which it named, can be gone.
    await store.put("/dir/a", entry())
    await store.set_partial_dir("/dir", [("b", entry("b"))])
    assert await store.set_dir("/dir", []) == [Evicted("/dir/b", folder=False)]
    assert (await store.get("/dir/a")).entry is not None


@pytest.mark.asyncio
async def test_a_relist_after_invalidate_still_evicts(store):
    await store.set_dir("/dir", [("a", entry()), ("b", entry("b"))])
    await store.invalidate()
    assert (await store.list_dir("/dir")).status == LookupStatus.EXPIRED
    assert await store.set_dir(
        "/dir", [("b", entry("b"))]) == [Evicted("/dir/a", folder=False)]
    assert (await store.get("/dir/a")).status == LookupStatus.NOT_FOUND


@pytest.mark.asyncio
async def test_a_relist_diffs_against_a_pending_seed(store):
    store.seed({
        "/dir/a": entry(),
        "/dir/b": entry("b")
    }, {"/dir": ["/dir/a", "/dir/b"]},
               datetime.now(timezone.utc) + timedelta(hours=1))
    assert await store.set_dir(
        "/dir", [("b", entry("b"))]) == [Evicted("/dir/a", folder=False)]


@pytest.mark.asyncio
async def test_a_dropped_listed_folder_without_a_folder_row_is_a_folder(store):
    # Classified by whether it holds a listing, not by its row's type.
    await store.set_dir("/dir", [("sub", entry("sub"))])
    await store.set_dir("/dir/sub", [("x", entry("x"))])
    assert await store.set_dir("/dir",
                               []) == [Evicted("/dir/sub", folder=True)]
    assert (await store.get("/dir/sub/x")).status == LookupStatus.NOT_FOUND


@pytest.mark.asyncio
async def test_a_relist_after_invalidate_dir_still_evicts(store):
    # Dropping a listing (a warm, a mutation) must not throw away what the
    # next re-list compares against.
    await store.set_dir("/dir", [("a", entry()), ("sub", folder("sub"))])
    await store.invalidate_dir("/dir")
    assert (await store.list_dir("/dir")).status == LookupStatus.NOT_FOUND
    assert await store.set_dir("/dir", []) == [
        Evicted("/dir/a", folder=False),
        Evicted("/dir/sub", folder=True)
    ]
    assert await store.set_dir("/dir", []) == []


@pytest.mark.asyncio
async def test_a_window_after_invalidate_dir_evicts_nothing(store):
    await store.set_dir("/dir", [("a", entry())])
    await store.invalidate_dir("/dir")
    assert await store.set_dir("/dir", [], window=True) == []
    assert await store.set_dir("/dir", []) == []


@pytest.mark.asyncio
async def test_a_partial_after_invalidate_dir_keeps_the_tombstone(store):
    await store.set_dir("/dir", [("a", entry()), ("b", entry("b"))])
    await store.invalidate_dir("/dir")
    await store.set_partial_dir("/dir", [("b", entry("b"))])
    assert await store.set_dir(
        "/dir", [("b", entry("b"))]) == [Evicted("/dir/a", folder=False)]


@pytest.mark.asyncio
async def test_invalidate_prefix_keeps_an_existing_tombstone(store):
    # A warm resolving a folder drops its parent's listing and then the
    # folder's own prefix before listing it; the evidence has to survive
    # that cascade or the re-list finds nothing gone.
    await store.set_dir("/dir", [("a", entry()), ("b", entry("b"))])
    await store.invalidate_dir("/dir")
    await store.invalidate_prefix("/dir")
    assert await store.set_dir(
        "/dir", [("a", entry())]) == [Evicted("/dir/b", folder=False)]


@pytest.mark.asyncio
async def test_invalidate_entry_preserves_children_for_relist(store):
    await store.put("/dir", entry("dir"))
    await store.set_dir("/dir", [("a", entry())])
    await store.invalidate_entry("/dir")
    assert (await store.get("/dir")).status == LookupStatus.NOT_FOUND
    assert (await store.list_dir("/dir")).entries == ["/dir/a"]
    assert await store.set_dir("/dir", []) == [Evicted("/dir/a", folder=False)]


@pytest.mark.asyncio
async def test_prefix_invalidation_preserves_excluded_subtrees(store):
    for path in ["/dir/nested", "/dir/nested/sub", "/dir/nested2"]:
        await store.put(path, entry(path))
        await store.set_dir(path, [("a", entry())])
    await store.invalidate_prefix("/dir", excluded=("/dir/nested", ))
    for path in ["/dir/nested", "/dir/nested/sub"]:
        assert (await store.get(path)).entry is not None
        assert (await store.list_dir(path)).entries == [path + "/a"]
    assert (await store.get("/dir/nested2/a")).status == LookupStatus.NOT_FOUND
