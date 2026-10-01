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
import logging
from urllib.parse import parse_qs

import pytest
from fakeredis.aioredis import FakeRedis

from mirage.accessor.hf_hub import HfRepoConfig
from mirage.cache.index.constants import LISTING_TRUST_WINDOW
from mirage.cache.index.ram import RAMIndexCacheStore
from mirage.cache.index.redis import RedisIndexCacheStore
from mirage.cache.index.scope import command_scope
from mirage.core.api.client import RetryPolicy
from mirage.core.hf_hub.stat import stat
from mirage.types import (
    ListingVersion,
    MountMode,
    PathSpec,
    ReadPolicy,
    ReadSpec,
)
from mirage.vfs.hf_models import HfModelsVFS
from mirage.vfs.loader import load_attr
from mirage.vfs.ram import RAMVFS
from mirage.vfs.registry import REGISTRY, build_vfs
from mirage.workspace import Workspace
from mirage.workspace.mount import Mount
from mirage.workspace.reconcile import Reconciler
from tests.fixtures.hf_hub_api import FakeHub, serve

REPO = ("models", "acme/widget")
ROOT = PathSpec(virtual="/m", directory="/m", vfs_path="")
LISTED = b"b.txt\n"
GROWN = b"b.txt\nnew.txt\n"


def _hub() -> FakeHub:
    return FakeHub(
        repos={REPO: {"a.txt": b"alpha\n", "docs/sub/b.txt": b"bravo\n"}}
    )


def _vfs(hub: FakeHub, revision: str | None = None):
    config = {"repo_id": "acme/widget", "endpoint": hub.url}
    if revision is not None:
        config["revision"] = revision
    return build_vfs("hf_models", config)


def _ws(vfs, policy: ReadPolicy = ReadPolicy.FRESH, index=None) -> Workspace:
    ws = Workspace(
        {
            "/m": Mount(
                vfs=vfs,
                mode=MountMode.READ,
                read=ReadSpec(policy=policy, ttl=600),
            ),
            "/r": (RAMVFS(), MountMode.WRITE),
        }
    )
    if index is not None:
        ws.mount("/m").index_store = index
    return ws


async def _out(ws: Workspace, line: str) -> bytes:
    result = await asyncio.wait_for(ws.shell(line), 10)
    out = await result.materialize_stdout()
    err = await result.stderr_str()
    assert (result.exit_code, err) == (0, ""), line
    return out


def _counts(hub: FakeHub) -> tuple[int, int, int, int]:
    return (
        hub.count("revision"),
        hub.count("tree"),
        hub.count("paths_info"),
        hub.count("resolve"),
    )


def _revs(hub: FakeHub, route: str) -> set[str]:
    return {rev for name, _, rev, _ in hub.log if name == route}


def _add(hub: FakeHub) -> None:
    hub.repos[REPO]["docs/sub/new.txt"] = b"new\n"


async def _stored(ws: Workspace, key: str = "/m") -> str | None:
    return (await ws.mount("/m").index_store.list_dir(key)).version


@pytest.mark.parametrize("name", ["hf_models", "hf_datasets", "hf_spaces"])
def test_every_hub_repo_kind_declares_one_version_for_the_mount(name):
    vfs_cls = load_attr(REGISTRY[name].vfs_path)
    assert vfs_cls.listing_version is ListingVersion.MOUNT


# The check asks the revision object trimmed to its sha, about 110 bytes
# against the whole sibling list.
@pytest.mark.asyncio
async def test_the_head_is_asked_with_expand_sha():
    with serve(_hub()) as hub:
        ws = _ws(_vfs(hub))
        try:
            await _out(ws, "ls /m")
            await _out(ws, "ls /m")
            asked = [q for name, _, _, q in hub.log if name == "revision"]
            assert len(asked) == 2
            assert all(parse_qs(q) == {"expand[]": ["sha"]} for q in asked)
        finally:
            await ws.close()


# The refill walks the tree at the commit the head named; every other
# route stays on the branch the mount reads.
@pytest.mark.asyncio
async def test_the_refill_walks_the_tree_at_the_head_it_resolved():
    with serve(_hub()) as hub:
        vfs = _vfs(hub)
        ws = _ws(vfs)
        try:
            head = hub.head(REPO)
            await _out(ws, "ls /m")
            await _out(ws, "cat /m/a.txt")
            await _out(ws, "cat /m/a.txt")
            assert _revs(hub, "tree") == {head}
            assert _revs(hub, "paths_info") == {"main"}
            assert _revs(hub, "resolve") == {"main"}
            assert vfs.accessor.revision == "main"
            assert await _stored(ws) == head
        finally:
            await ws.close()


# The listing an implied folder sits in names it, with a row of its own,
# so a nested folder is listed like any other.
@pytest.mark.asyncio
async def test_a_folder_implied_by_a_deeper_file_is_listed():
    with serve(_hub()) as hub:
        ws = _ws(_vfs(hub))
        try:
            assert await _out(ws, "ls /m") == b"a.txt\ndocs\n"
            assert await _out(ws, "ls /m/docs") == b"sub\n"
        finally:
            await ws.close()


# Named counts (revision, tree, paths_info, resolve).
@pytest.mark.asyncio
async def test_an_unchanged_second_command_costs_one_revision():
    with serve(_hub()) as hub:
        ws = _ws(_vfs(hub))
        try:
            await _out(ws, "ls /m")
            hub.log.clear()
            assert await _out(ws, "ls /m/docs/sub") == LISTED
            assert _counts(hub) == (1, 0, 0, 0)
        finally:
            await ws.close()


# The gate's check misses, and the refill asks the head once more for the
# commit it walks the tree at.
@pytest.mark.asyncio
async def test_a_changed_second_command_checks_then_walks_once():
    with serve(_hub()) as hub:
        ws = _ws(_vfs(hub))
        try:
            await _out(ws, "ls /m")
            _add(hub)
            hub.log.clear()
            assert await _out(ws, "ls /m/docs/sub") == GROWN
            assert _counts(hub) == (2, 1, 0, 0)
        finally:
            await ws.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("line", ["find /m -type f", "ls -R /m"])
async def test_a_walk_after_an_outside_add_sees_it(line):
    with serve(_hub()) as hub:
        ws = _ws(_vfs(hub))
        try:
            await _out(ws, "ls /m")
            hub.log.clear()
            assert b"new.txt" not in await _out(ws, line)
            assert _counts(hub) == (1, 0, 0, 0)
            _add(hub)
            hub.log.clear()
            assert b"new.txt" in await _out(ws, line)
            assert _counts(hub) == (2, 1, 0, 0)
        finally:
            await ws.close()


# A bounded mount's cold fill resolves the head too, so the version it
# stores always comes from a response.
@pytest.mark.asyncio
async def test_a_bounded_cold_fill_asks_the_head_once():
    with serve(_hub()) as hub:
        ws = _ws(_vfs(hub), policy=ReadPolicy.BOUNDED)
        try:
            await _out(ws, "ls /m")
            assert _counts(hub) == (1, 1, 0, 0)
            assert await _stored(ws) == hub.head(REPO)
            hub.log.clear()
            await _out(ws, "ls /m/docs/sub")
            assert _counts(hub) == (0, 0, 0, 0)
        finally:
            await ws.close()


# A second mount over a warm shared store has not loaded its tree; the
# gate's root stat asks the head once and never walks or loads the tree.
@pytest.mark.asyncio
async def test_a_root_stat_through_a_throwaway_index_never_walks():
    shared = RAMIndexCacheStore()
    with serve(_hub()) as hub:
        one = _ws(_vfs(hub), index=shared)
        two_vfs = _vfs(hub)
        two = _ws(two_vfs, index=shared)
        try:
            await _out(one, "ls /m")
            hub.log.clear()
            found = await two.mount("/m").execute_op(
                "stat", "/m", index=RAMIndexCacheStore()
            )
            assert found.fingerprint == hub.head(REPO)
            assert _counts(hub) == (1, 0, 0, 0)
            assert two_vfs.accessor.tree_loaded is False
        finally:
            await one.close()
            await two.close()


# The mount's own index answers the root from its listing, read past the
# gate, so a getattr of the root costs nothing however stale the trust is.
@pytest.mark.asyncio
@pytest.mark.parametrize("scoped", [True, False])
async def test_a_root_stat_through_the_mount_index_reads_it_ungated(
    monkeypatch, scoped
):
    now = [100.0]
    monkeypatch.setattr("mirage.cache.manager._now", lambda: now[0])
    with serve(_hub()) as hub:
        ws = _ws(_vfs(hub))
        try:
            await _out(ws, "ls /m")
            stored = await _stored(ws)
            now[0] += LISTING_TRUST_WINDOW * 2
            hub.log.clear()
            mount = ws.mount("/m")
            if scoped:
                async with command_scope():
                    found = await stat(mount.vfs.accessor, ROOT, mount.index)
            else:
                found = await stat(mount.vfs.accessor, ROOT, mount.index)
            assert stored is not None
            assert found.fingerprint == stored
            assert _counts(hub) == (0, 0, 0, 0)
        finally:
            await ws.close()


@pytest.mark.asyncio
async def test_an_expired_root_listing_names_no_version():
    with serve(_hub()) as hub:
        ws = _ws(_vfs(hub), policy=ReadPolicy.BOUNDED)
        try:
            await _out(ws, "ls /m")
            mount = ws.mount("/m")
            await mount.index_store.invalidate()
            hub.log.clear()
            found = await stat(mount.vfs.accessor, ROOT, mount.index)
            assert found.fingerprint is None
            assert _counts(hub) == (0, 0, 0, 0)
        finally:
            await ws.close()


# A refused head names no version, and the root stat never falls into a
# refill of the throwaway index.
@pytest.mark.asyncio
@pytest.mark.parametrize("refusal", [(404, "RevisionNotFound"), (401, "")])
async def test_a_refused_head_names_no_version_and_walks_nothing(refusal):
    with serve(_hub()) as hub:
        vfs = _vfs(hub)
        ws = _ws(vfs)
        try:
            await _out(ws, "ls /m")
            hub.fail["revision"] = refusal
            hub.log.clear()
            found = await stat(vfs.accessor, ROOT, RAMIndexCacheStore())
            assert found.fingerprint is None
            assert (hub.count("revision"), hub.count("tree")) == (1, 0)
        finally:
            await ws.close()


SHA = "0123456789abcdef0123456789abcdef01234567"


def test_the_pin_is_the_effective_revision_lowercased():

    def pin(**kwargs):
        return HfModelsVFS(
            HfRepoConfig(repo_id="acme/widget", **kwargs)
        ).listings_pin

    assert pin(revision=SHA.upper()) == SHA
    assert pin(revision="b" * 64) == "b" * 64
    assert pin(revision="main") is None
    assert pin() is None
    assert pin(revision=SHA[:-1]) is None


# Pinned to a commit given in uppercase: the refill still resolves the
# head, stores the lowercase sha the Hub answers, and the next command
# serves it with no request.
@pytest.mark.asyncio
async def test_a_mount_pinned_to_a_commit_serves_its_listing_unchecked():
    with serve(_hub()) as hub:
        head = hub.head(REPO)
        ws = _ws(_vfs(hub, revision=head.upper()))
        try:
            assert await _out(ws, "ls /m/docs/sub") == LISTED
            assert _counts(hub) == (1, 1, 0, 0)
            assert await _stored(ws) == head
            hub.log.clear()
            assert await _out(ws, "ls /m/docs/sub") == LISTED
            assert _counts(hub) == (0, 0, 0, 0)
        finally:
            await ws.close()


# A mount pinned to an older commit, over a store a `main` mount filled,
# must not serve main's listing just because it is pinned.
@pytest.mark.asyncio
async def test_a_pinned_mount_never_serves_another_revisions_listing():
    with serve(_hub()) as hub:
        old = hub.head(REPO)
        shared = RAMIndexCacheStore()
        main = _ws(_vfs(hub), index=shared)
        try:
            await _out(main, "ls /m/docs/sub")
            _add(hub)
            assert await _out(main, "ls /m/docs/sub") == GROWN
        finally:
            await main.close()
        pinned = _ws(_vfs(hub, revision=old), index=shared)
        try:
            hub.log.clear()
            assert await _out(pinned, "ls /m/docs/sub") == LISTED
            # The check answers the pin, not main's head: a refill at it.
            assert _counts(hub) == (2, 1, 0, 0)
            hub.log.clear()
            assert await _out(pinned, "ls /m/docs/sub") == LISTED
            assert _counts(hub) == (0, 0, 0, 0)
        finally:
            await pinned.close()


# A branch named with 40 hex characters is not a commit: it is stored at
# the head its revision answered, so an outside change is always seen.
@pytest.mark.asyncio
async def test_a_hex_branch_name_is_never_served_as_a_pin():
    branch = "a" * 40
    with serve(_hub()) as hub:
        hub.branches.add(branch)
        ws = _ws(_vfs(hub, revision=branch))
        try:
            assert ws.mount("/m").vfs.listings_pin == branch
            assert await _out(ws, "ls /m/docs/sub") == LISTED
            _add(hub)
            hub.log.clear()
            assert await _out(ws, "ls /m/docs/sub") == GROWN
            assert _counts(hub) != (0, 0, 0, 0)
        finally:
            await ws.close()


# A commit landing between the head and the tree walk: the tree is walked
# at the head that was named, so the rows match their version, and the
# next command's check sees the change.
@pytest.mark.asyncio
async def test_a_commit_between_the_head_and_the_walk_is_caught_next_command():
    with serve(_hub()) as hub:
        ws = _ws(_vfs(hub))
        try:
            old = hub.head(REPO)
            hub.after_revision = lambda: _add(hub)
            assert await _out(ws, "ls /m/docs/sub") == LISTED
            hub.after_revision = None
            assert _revs(hub, "tree") == {old}
            assert await _stored(ws) == old
            hub.log.clear()
            assert await _out(ws, "ls /m/docs/sub") == GROWN
            assert _counts(hub) == (2, 1, 0, 0)
        finally:
            await ws.close()


# A revision the Hub does not know: the refusal wording is the one the
# tree walk gave before the head was asked first.
@pytest.mark.asyncio
async def test_a_bad_revision_reads_as_permission_denied():
    with serve(_hub()) as hub:
        ws = _ws(_vfs(hub, revision="f" * 40))
        try:
            ls = await ws.shell("ls /m")
            assert (ls.exit_code, await ls.stderr_str()) == (
                2,
                "ls: cannot open directory '/m': Permission denied\n",
            )
            cat = await ws.shell("cat /m/a.txt")
            assert (cat.exit_code, await cat.stderr_str()) == (
                1,
                "cat: /m/a.txt: Permission denied\n",
            )
            assert await _out(ws, "stat -c %n /m") == b"/m\n"
        finally:
            await ws.close()


# On Redis a versioned listing reads EXPIRED when a listed child has no
# row; every folder the tree implies has one, so a second command over
# nested folders is served on the version alone.
@pytest.mark.asyncio
async def test_an_unchanged_listing_on_redis_costs_one_revision():
    client = FakeRedis()
    store = RedisIndexCacheStore(client=client)
    with serve(_hub()) as hub:
        ws = _ws(_vfs(hub), index=store)
        try:
            await _out(ws, "ls /m")
            hub.log.clear()
            assert await _out(ws, "ls /m /m/docs /m/docs/sub") == (
                b"/m:\na.txt\ndocs\n\n/m/docs:\nsub\n\n/m/docs/sub:\nb.txt\n"
            )
            assert _counts(hub) == (1, 0, 0, 0)
        finally:
            await ws.close()
            await client.aclose()


# A Hub that cannot be reached answers EXPIRED at the gate, logged, and the
# listing stays stored for the re-list to diff.
@pytest.mark.asyncio
async def test_an_unreachable_hub_keeps_the_listing(caplog, monkeypatch):
    monkeypatch.setattr(
        "mirage.core.hf_hub.client.RETRY", RetryPolicy(retry_transport=False)
    )
    caplog.set_level(logging.DEBUG, logger="mirage.workspace.reconcile")
    with serve(_hub()) as hub:
        ws = _ws(_vfs(hub))
        await _out(ws, "ls /m")
    try:
        mount = ws.mount("/m")
        stored = await mount.index_store.list_dir("/m/docs/sub")
        rec = Reconciler(ws.cache, ws.namespace)
        async with command_scope():
            assert (
                await rec.may_serve_listing(
                    mount, "/m/docs/sub", stored.version
                )
                is False
            )
        kept = await mount.index_store.list_dir("/m/docs/sub")
        assert kept.entries == stored.entries
        assert "listing check failed" in caplog.text
    finally:
        await ws.close()


# A FUSE or programmatic read belongs to no command: it trusts a listing
# for the window, then pays one version check, never a tree walk.
@pytest.mark.asyncio
async def test_an_unscoped_read_checks_once_past_the_window(monkeypatch):
    now = [100.0]
    monkeypatch.setattr("mirage.cache.manager._now", lambda: now[0])
    readdir = PathSpec(
        virtual="/m/docs/sub", directory="/m/docs/sub", vfs_path="docs/sub"
    )
    one = PathSpec(
        virtual="/m/docs/sub/b.txt",
        directory="/m/docs/sub",
        vfs_path="docs/sub/b.txt",
    )
    with serve(_hub()) as hub:
        ws = _ws(_vfs(hub))
        try:
            await _out(ws, "ls /m")
            hub.log.clear()
            listed, _ = await ws.dispatch("readdir", readdir)
            assert listed == ["/m/docs/sub/b.txt"]
            await ws.dispatch("stat", one)
            assert _counts(hub) == (0, 0, 0, 0)
            now[0] += LISTING_TRUST_WINDOW
            await ws.dispatch("readdir", readdir)
            await ws.dispatch("stat", one)
            assert _counts(hub) == (1, 0, 0, 0)
        finally:
            await ws.close()
