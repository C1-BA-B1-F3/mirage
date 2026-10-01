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

import pytest

from mirage.cache.index.scope import command_scope
from mirage.types import ListingVersion, ReadPolicy, ReadSpec
from mirage.vfs.base import BaseVFS
from mirage.vfs.loader import load_attr
from mirage.vfs.registry import REGISTRY, known_vfs_names
from mirage.workspace import Workspace
from mirage.workspace.reconcile import Reconciler
from tests.fixtures.versioned_vfs import VersionedVFS

# A declarer gets a harness proving that its check and its fill agree, so
# the gate's stat and the stored version are one kind of token. None ships
# yet; each declaring backend adds its row with its declaration.
HARNESSES: dict[str, str] = {}


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
    assert sorted(HARNESSES) == []


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
