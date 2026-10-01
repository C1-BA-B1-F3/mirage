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
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass

import pytest

from mirage.cache.index.ram import RAMIndexCacheStore
from mirage.cache.index.scope import command_scope
from mirage.types import ListingVersion, MountMode, ReadPolicy, ReadSpec
from mirage.vfs.base import BaseVFS
from mirage.vfs.loader import load_attr
from mirage.vfs.registry import REGISTRY, build_vfs, known_vfs_names
from mirage.workspace import Workspace
from mirage.workspace.mount import Mount
from mirage.workspace.reconcile import Reconciler
from tests.fixtures.github_api import FakeGitHub, serve
from tests.fixtures.versioned_vfs import VersionedVFS


@dataclass
class Harness:
    """One declarer, filled and ready to be checked.

    Args:
        ws (Workspace): a fresh workspace with the backend at ``/m``.
        key (str): the listing key its check covers (the mount root for
            MOUNT, a folder for FOLDER).
        nested (str): a folder below the root, listed by the same fill.
        counts (Callable): (checks, refills) sent to the backend so far.
        change (Callable): change the backend outside mirage.
    """

    ws: Workspace
    key: str
    nested: str
    counts: Callable[[], tuple[int, int]]
    change: Callable[[], None]


@asynccontextmanager
async def _github() -> AsyncIterator[Harness]:
    hub = FakeGitHub(files={"docs/sub/a.txt": b"a\n", "top.txt": b"t\n"})
    with serve(hub):
        vfs = build_vfs(
            "github",
            {
                "token": "t",
                "owner": "o",
                "repo": "r",
                "ref": "main",
                "base_url": hub.url,
            },
        )
        ws = Workspace(
            {
                "/m": Mount(
                    vfs=vfs,
                    mode=MountMode.READ,
                    read=ReadSpec(policy=ReadPolicy.FRESH, ttl=600),
                )
            }
        )
        try:
            yield Harness(
                ws=ws,
                key="/m",
                nested="/m/docs/sub",
                counts=lambda: (hub.count("dir"), hub.count("recursive")),
                change=lambda: hub.files.__setitem__("docs/new.txt", b"n\n"),
            )
        finally:
            await ws.close()


# A declarer gets a harness proving that its check and its fill agree, so
# the gate's stat and the stored version are one kind of token. Each
# declaring backend adds its row with its declaration.
HARNESSES: dict[str, Callable[[], AsyncIterator[Harness]]] = {
    "github": _github,
}


def _declared() -> set[str]:
    declared = set()
    for name in known_vfs_names():
        entry = REGISTRY.get(name)
        if entry is None:
            continue
        if load_attr(entry.vfs_path).listing_version != ListingVersion.NONE:
            declared.add(name)
    return declared


def test_every_declaring_backend_has_a_harness():
    assert _declared() == set(HARNESSES)


def test_the_harness_roster_is_pinned():
    # A literal, not the derived set: the expectation must not move with
    # the registry it checks.
    assert sorted(HARNESSES) == ["github"]


def test_the_base_declares_no_version_and_no_pin():
    assert BaseVFS.listing_version is ListingVersion.NONE
    assert BaseVFS.listings_pin is None
    assert [m.value for m in ListingVersion] == ["none", "mount", "folder"]


def _undeclared() -> list[str]:
    declared = _declared()
    return sorted(
        name
        for name in known_vfs_names()
        if name in REGISTRY and name not in declared
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("name", _undeclared())
async def test_an_undeclaring_backend_never_pays_a_version_check(name):
    vfs = VersionedVFS()
    vfs.listing_version = load_attr(REGISTRY[name].vfs_path).listing_version
    ws = Workspace({"/m/": vfs}, read=ReadSpec(policy=ReadPolicy.FRESH))
    try:
        mount = ws.namespace.mount_for("/m/a")
        await mount.index_store.set_dir("/m/a", [], version="v1")
        rec = Reconciler(ws.cache, ws.namespace)
        async with command_scope():
            assert await rec.may_serve_listing(mount, "/m/a", "v1") is False
        assert vfs.stats == []
    finally:
        await ws.close()


async def _shell(ws: Workspace, line: str) -> None:
    result = await asyncio.wait_for(ws.shell(line), 10)
    await result.materialize_stdout()
    assert (result.exit_code, await result.stderr_str()) == (0, ""), line


async def _check_contract(name: str) -> None:
    async with HARNESSES[name]() as harness:
        ws = harness.ws
        mount = ws.mount(harness.key)
        await _shell(ws, f"ls {harness.key} {harness.nested}")
        store = mount.index_store
        stored = (await store.list_dir(harness.key)).version
        assert stored is not None
        assert (await store.list_dir(harness.nested)).version is not None
        remote = await mount.execute_op(
            "stat", harness.key, index=RAMIndexCacheStore()
        )
        assert remote.fingerprint == stored
        before = harness.counts()
        await _shell(ws, f"ls {harness.key} {harness.nested}")
        checks, refills = (
            now - then for now, then in zip(harness.counts(), before)
        )
        assert (checks, refills) == (1, 0)
        assert mount.vfs.listing_version == type(mount.vfs).listing_version
        harness.change()
        moved = await mount.execute_op(
            "stat", harness.key, index=RAMIndexCacheStore()
        )
        assert moved.fingerprint is not None
        assert moved.fingerprint != stored


@pytest.mark.asyncio
@pytest.mark.parametrize("name", sorted(HARNESSES))
async def test_a_declarers_check_answers_what_its_fill_stored(name):
    await _check_contract(name)


@pytest.mark.asyncio
async def test_the_contract_goes_red_on_github_seeding_a_tree_sha(monkeypatch):
    # github made to store each listing at the root tree's sha while its
    # check answers the head commit: one kind of token on each side.
    original = RAMIndexCacheStore.seed

    def seed(self, entries, children, expires_at, *, version=None):
        tree = None if version is None else "f" * 40
        original(self, entries, children, expires_at, version=tree)

    monkeypatch.setattr(RAMIndexCacheStore, "seed", seed)
    with pytest.raises(AssertionError):
        await _check_contract("github")
