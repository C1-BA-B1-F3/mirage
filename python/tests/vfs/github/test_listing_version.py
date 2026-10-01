# ========= Copyright 2026 @ Strukto.AI All Rights Reserved. =========
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Nless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ========= Copyright 2026 @ Strukto.AI All Rights Reserved. =========

import asyncio
import logging

import pytest
from fakeredis.aioredis import FakeRedis

from mirage.cache.index.constants import LISTING_TRUST_WINDOW
from mirage.cache.index.ram import RAMIndexCacheStore
from mirage.cache.index.redis import RedisIndexCacheStore
from mirage.cache.index.scope import command_scope
from mirage.core.github.config import GitHubConfig
from mirage.core.github.stat import stat
from mirage.core.github.watch import GitHubWalk
from mirage.types import (
    ListingVersion,
    MountMode,
    PathSpec,
    ReadPolicy,
    ReadSpec,
)
from mirage.vfs.github import GitHubVFS
from mirage.vfs.ram import RAMVFS
from mirage.vfs.registry import build_vfs
from mirage.workspace import Workspace
from mirage.workspace.mount import Mount
from mirage.workspace.reconcile import Reconciler
from tests.fixtures.github_api import FakeGitHub, serve

ROOT = PathSpec(virtual="/gh", directory="/gh", vfs_path="")
LISTED = b"a.txt\nb.txt\nc.txt\n"
GROWN = b"a.txt\nb.txt\nc.txt\nnew.txt\n"


def _three() -> FakeGitHub:
    return FakeGitHub(
        files={f"d{i}/{n}.txt": b"x\n" for i in (1, 2, 3) for n in "abc"}
    )


def _vfs(hub: FakeGitHub, ref: str = "main"):
    return build_vfs(
        "github",
        {
            "token": "t",
            "owner": "o",
            "repo": "r",
            "ref": ref,
            "base_url": hub.url,
        },
    )


def _ws(vfs, policy: ReadPolicy = ReadPolicy.FRESH, index=None) -> Workspace:
    ws = Workspace(
        {
            "/gh": Mount(
                vfs=vfs,
                mode=MountMode.READ,
                read=ReadSpec(policy=policy, ttl=600),
            ),
            "/r": (RAMVFS(), MountMode.WRITE),
        }
    )
    if index is not None:
        ws.mount("/gh").index_store = index
    return ws


async def _out(ws: Workspace, line: str, session_id: str | None = None):
    kwargs = {} if session_id is None else {"session_id": session_id}
    result = await asyncio.wait_for(ws.shell(line, **kwargs), 10)
    out = await result.materialize_stdout()
    err = await result.stderr_str()
    assert (result.exit_code, err) == (0, ""), line
    return out


async def _stored(ws: Workspace, key: str = "/gh") -> str | None:
    return (await ws.mount("/gh").index_store.list_dir(key)).version


def test_github_declares_one_version_for_the_whole_mount():
    assert GitHubVFS.listing_version is ListingVersion.MOUNT


# The mount's own index answers the root from its listing, read past the
# gate, so a getattr of the root costs nothing however stale the trust is.
@pytest.mark.asyncio
@pytest.mark.parametrize("scoped", [True, False])
async def test_a_root_stat_through_the_mount_index_reads_it_ungated(
    monkeypatch, scoped
):
    now = [100.0]
    monkeypatch.setattr("mirage.cache.manager._now", lambda: now[0])
    with serve(_three()) as hub:
        ws = _ws(_vfs(hub))
        try:
            await _out(ws, "ls /gh")
            stored = await _stored(ws)
            now[0] += LISTING_TRUST_WINDOW * 2
            hub.log.clear()
            mount = ws.mount("/gh")
            if scoped:
                async with command_scope():
                    found = await stat(mount.vfs.accessor, ROOT, mount.index)
            else:
                found = await stat(mount.vfs.accessor, ROOT, mount.index)
            assert stored is not None
            assert found.fingerprint == stored
            assert hub.counts() == (0, 0, 0)
        finally:
            await ws.close()


# An expired root listing names no version and asks nothing; a refused
# head names none either, and never falls into a refill of the index.
@pytest.mark.asyncio
async def test_an_expired_root_listing_names_no_version():
    with serve(_three()) as hub:
        ws = _ws(_vfs(hub), policy=ReadPolicy.BOUNDED)
        try:
            await _out(ws, "ls /gh")
            mount = ws.mount("/gh")
            await mount.index_store.invalidate()
            hub.log.clear()
            found = await stat(mount.vfs.accessor, ROOT, mount.index)
            assert found.fingerprint is None
            assert hub.counts() == (0, 0, 0)
        finally:
            await ws.close()


# An add outside mirage moves the head, so the next command's one check
# misses and the tree is fetched once; ls and a glob both see the file.
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "line,expected",
    [
        ("ls /gh/d1", GROWN),
        (
            "echo /gh/d1/*",
            b"/gh/d1/a.txt /gh/d1/b.txt /gh/d1/c.txt /gh/d1/new.txt\n",
        ),
    ],
)
async def test_an_outside_add_is_seen_after_one_check_and_one_walk(
    line, expected
):
    with serve(_three()) as hub:
        ws = _ws(_vfs(hub))
        try:
            await _out(ws, "ls /gh")
            hub.files["d1/new.txt"] = b"new\n"
            hub.log.clear()
            assert await _out(ws, line) == expected
            assert hub.counts() == (1, 1, 0)
        finally:
            await ws.close()


# The version is the head the tree response itself named, so a commit
# landing right after that response is a mismatch for the next command.
@pytest.mark.asyncio
async def test_a_commit_after_the_tree_response_is_caught_next_command():
    with serve(_three()) as hub:
        ws = _ws(_vfs(hub))
        try:
            hub.after_recursive = lambda: hub.files.setdefault(
                "d1/new.txt", b"new\n"
            )
            assert await _out(ws, "ls /gh/d1") == LISTED
            hub.after_recursive = None
            hub.log.clear()
            assert await _out(ws, "ls /gh/d1") == GROWN
            assert hub.counts() == (1, 1, 0)
        finally:
            await ws.close()


# A second workspace refills the index both share, so the first one's
# in-memory tree is older than its index. ls answers from the index and pays
# nothing for that; find and grep walk the tree, so they refill it first.
@pytest.mark.asyncio
async def test_a_tree_older_than_a_shared_index_is_refilled_for_walks():
    with serve(_three()) as hub:
        shared = RAMIndexCacheStore()
        one, two = _ws(_vfs(hub), index=shared), _ws(_vfs(hub), index=shared)
        try:
            await _out(one, "ls /gh")
            hub.files["d1/new.txt"] = b"new x\n"
            await _out(two, "ls /gh/d1")
            hub.log.clear()
            assert await _out(one, "ls /gh/d1") == GROWN
            assert hub.counts() == (1, 0, 0)
            hub.log.clear()
            found = await _out(one, "find /gh -name new.txt")
            assert found == b"/gh/d1/new.txt\n"
            assert hub.counts() == (1, 1, 0)
            assert b"/gh/d1/new.txt" in await _out(one, "grep -rl x /gh")
        finally:
            await one.close()
            await two.close()


SHA = "0123456789abcdef0123456789abcdef01234567"


# A full-hex ref pins every listing: the stored version is the pin, so
# the next command serves it with no request. The ref is the effective one,
# the kwarg over the config, and compared lowercased.
def test_the_pin_is_the_effective_ref_lowercased():
    config = GitHubConfig(token="t", owner="o", repo="r", base_url="x")
    assert GitHubVFS(config, ref=SHA.upper()).listings_pin == SHA
    assert GitHubVFS(config).listings_pin is None
    assert GitHubVFS(config, ref="main").listings_pin is None
    pinned = GitHubConfig(
        token="t", owner="o", repo="r", ref=SHA, base_url="x"
    )
    assert GitHubVFS(pinned).listings_pin == SHA


@pytest.mark.asyncio
async def test_a_mount_pinned_to_a_commit_serves_its_listing_unchecked():
    with serve(_three()) as hub:
        head = hub.head()
        ws = _ws(_vfs(hub, ref=head.upper()))
        try:
            assert await _out(ws, "ls /gh/d1") == LISTED
            assert await _stored(ws) == head
            hub.log.clear()
            assert await _out(ws, "ls /gh/d1") == LISTED
            assert hub.counts() == (0, 0, 0)
        finally:
            await ws.close()


# A mount pinned to an older commit, over a store a `main` mount
# filled, must not serve main's listing just because it is pinned.
@pytest.mark.asyncio
async def test_a_pinned_mount_never_serves_another_refs_listing():
    with serve(_three()) as hub:
        old = hub.head()
        shared = RAMIndexCacheStore()
        main = _ws(_vfs(hub), index=shared)
        try:
            await _out(main, "ls /gh/d1")
            hub.files["d1/new.txt"] = b"new\n"
            assert await _out(main, "ls /gh/d1") == GROWN
        finally:
            await main.close()
        pinned = _ws(_vfs(hub, ref=old), index=shared)
        try:
            hub.log.clear()
            assert await _out(pinned, "ls /gh/d1") == LISTED
            assert hub.count("dir") == 1
        finally:
            await pinned.close()


# A ref shaped like a commit is not one. A branch named with 40 hex
# characters, or a 64-hex name, is stored at the head its tree answered, so
# it never matches the ref and an outside change is always seen.
@pytest.mark.asyncio
@pytest.mark.parametrize("ref", ["a" * 40, "b" * 64])
@pytest.mark.parametrize("truncated", [False, True])
async def test_a_hex_branch_name_is_never_served_as_a_pin(ref, truncated):
    with serve(_three()) as hub:
        hub.ref = ref
        hub.truncated_recursive = truncated
        ws = _ws(_vfs(hub, ref=ref))
        try:
            assert ws.mount("/gh").vfs.listings_pin == ref
            assert await _out(ws, "ls /gh/d1") == LISTED
            hub.files["d1/new.txt"] = b"new\n"
            hub.log.clear()
            assert await _out(ws, "ls /gh/d1") == GROWN
            assert hub.counts() != (0, 0, 0)
        finally:
            await ws.close()


# A truncated tree stores no version, pinned or not, so it re-lists
# folder by folder as it did before versions existed.
@pytest.mark.asyncio
async def test_a_truncated_pinned_mount_relists_like_an_unpinned_one():
    costs = []
    for pinned in (False, True):
        with serve(_three()) as hub:
            hub.truncated_recursive = True
            ws = _ws(_vfs(hub, ref=hub.head() if pinned else "main"))
            try:
                await _out(ws, "ls /gh/d1")
                assert await _stored(ws, "/gh/d1") is None
                hub.log.clear()
                assert await _out(ws, "ls /gh/d1") == LISTED
                costs.append((hub.counts(), hub.count("sha_dir")))
            finally:
                await ws.close()
    assert costs[0] == costs[1]


# A tree response that names no head stores no version, so the next
# command re-lists exactly as before versions existed.
@pytest.mark.asyncio
async def test_a_response_without_a_head_stores_no_version():
    with serve(_three()) as hub:
        hub.drop_sha = True
        ws = _ws(_vfs(hub))
        try:
            await _out(ws, "ls /gh")
            assert await _stored(ws) is None
            assert await _stored(ws, "/gh/d1") is None
            hub.log.clear()
            await _out(ws, "ls /gh/d1")
            assert hub.counts() == (0, 1, 0)
        finally:
            await ws.close()


# Tree walks check the version like a listing does, and refill on a miss.
@pytest.mark.asyncio
@pytest.mark.parametrize("line", ["find /gh", "du -a /gh"])
async def test_a_tree_walk_after_an_outside_add_checks_then_walks_once(line):
    with serve(_three()) as hub:
        ws = _ws(_vfs(hub))
        try:
            await _out(ws, "ls /gh")
            hub.files["d1/new.txt"] = b"new\n"
            hub.log.clear()
            assert b"/gh/d1/new.txt" in await _out(ws, line)
            assert hub.counts() == (1, 1, 0)
        finally:
            await ws.close()


# The watcher's walk reseats the tree, and stamps the head it answered,
# so a revert back to the index's head still refills the walked tree.
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "policy,cost",
    [
        (ReadPolicy.BOUNDED, (0, 1, 0)),
        (ReadPolicy.FRESH, (1, 1, 0)),
    ],
)
async def test_a_watched_tree_carries_the_head_it_was_walked_at(policy, cost):
    with serve(_three()) as hub:
        vfs = _vfs(hub)
        ws = _ws(vfs, policy=policy)
        try:
            await _out(ws, "ls /gh")
            hub.files["d1/new.txt"] = b"new\n"
            async for _ in GitHubWalk(vfs.accessor)(ROOT):
                pass
            assert vfs.accessor.tree_version == hub.head()
            del hub.files["d1/new.txt"]
            hub.log.clear()
            assert await _out(ws, "find /gh -name new.txt") == b""
            assert hub.counts() == cost
        finally:
            await ws.close()


# On Redis a versioned listing whose child row was evicted reads
# EXPIRED, and the reader refills rather than serving a hole.
@pytest.mark.asyncio
async def test_an_evicted_child_row_on_redis_refills_the_listing():
    client = FakeRedis()
    store = RedisIndexCacheStore(client=client)
    with serve(_three()) as hub:
        ws = _ws(_vfs(hub), index=store)
        try:
            await _out(ws, "ls /gh")
            await client.delete(store._entry_key("/gh/d1/a.txt"))
            hub.log.clear()
            assert await _out(ws, "ls /gh/d1") == LISTED
            assert hub.count("recursive") == 1
        finally:
            await ws.close()
            await client.aclose()


# The Redis store serves an unchanged listing on one check, the same as RAM.
@pytest.mark.asyncio
async def test_an_unchanged_listing_on_redis_costs_one_check():
    client = FakeRedis()
    store = RedisIndexCacheStore(client=client)
    with serve(_three()) as hub:
        ws = _ws(_vfs(hub), index=store)
        try:
            await _out(ws, "ls /gh")
            hub.log.clear()
            assert await _out(ws, "ls /gh/d1") == LISTED
            assert hub.counts() == (1, 0, 0)
        finally:
            await ws.close()
            await client.aclose()


# A backend that cannot be reached answers EXPIRED at the gate, logged,
# and the listing stays stored for the re-list to diff.
@pytest.mark.asyncio
async def test_an_unreachable_backend_keeps_the_listing(caplog):
    caplog.set_level(logging.DEBUG, logger="mirage.workspace.reconcile")
    with serve(_three()) as hub:
        ws = _ws(_vfs(hub))
        await _out(ws, "ls /gh")
    try:
        mount = ws.mount("/gh")
        stored = await mount.index_store.list_dir("/gh/d1")
        rec = Reconciler(ws.cache, ws.namespace)
        async with command_scope():
            assert (
                await rec.may_serve_listing(mount, "/gh/d1", stored.version)
                is False
            )
        kept = await mount.index_store.list_dir("/gh/d1")
        assert kept.entries == stored.entries
        assert "listing check failed" in caplog.text
    finally:
        await ws.close()
