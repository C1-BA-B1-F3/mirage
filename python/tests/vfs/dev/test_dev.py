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

import pytest

from mirage import Workspace
from mirage.commands.cli.types import CLISpec
from mirage.context import reset_current_session, set_current_session
from mirage.io.types import IOResult
from mirage.vfs.dev.dev import DevStore, DevVFS, _DevFiles
from mirage.vfs.ram import RAMVFS
from mirage.workspace.session.session import SessionState


def test_contains_dev_names_with_or_without_slash():
    files = _DevFiles()
    assert "/null" in files
    assert "null" in files
    assert "/zero" in files
    assert "zero" in files
    assert "/other" not in files


def test_synthetic_devices_use_empty_store_placeholders():
    files = _DevFiles()
    assert files["/null"] == b""
    assert files["/zero"] == b""
    with pytest.raises(KeyError):
        files["/missing"]


def test_set_on_active_device_is_discarded():
    files = _DevFiles()
    files["/null"] = b"overwrite"
    assert files["/null"] == b""
    assert files["/zero"] == b""


def test_delete_tombstones_a_synthetic_device():
    files = _DevFiles()
    del files["/null"]
    assert "/null" not in files
    assert list(files.keys()) == ["/zero"]
    assert len(files) == 1
    with pytest.raises(KeyError):
        files["/null"]
    with pytest.raises(KeyError):
        del files["/null"]


def test_set_after_delete_stores_real_bytes():
    files = _DevFiles()
    del files["/null"]
    files["/null"] = b"recreated"
    assert "/null" in files
    assert files["/null"] == b"recreated"
    assert list(files.keys()) == ["/zero", "/null"]
    assert len(files) == 2


def test_delete_of_recreated_file_removes_it_again():
    files = _DevFiles()
    del files["/null"]
    files["/null"] = b"recreated"
    del files["/null"]
    assert "/null" not in files
    assert list(files.keys()) == ["/zero"]


def test_non_device_names_store_for_real():
    files = _DevFiles()
    files["/custom"] = b"bytes"
    assert "/custom" in files
    assert files["/custom"] == b"bytes"
    assert list(files.keys()) == ["/null", "/zero", "/custom"]
    del files["/custom"]
    assert "/custom" not in files


def test_pop_mirrors_delete_semantics():
    files = _DevFiles()
    assert files.pop("/null") == b""
    assert "/null" not in files
    assert files.pop("/null", b"gone") == b"gone"
    files["/null"] = b"real"
    assert files.pop("/null") == b"real"
    assert "/null" not in files


def test_iterates_synthetic_then_real():
    files = _DevFiles()
    assert list(files) == ["/null", "/zero"]
    assert len(files) == 2


def test_dev_store_starts_with_synthetic_files_and_root():
    store = DevStore()
    assert list(store.files.keys()) == ["/null", "/zero"]
    assert "/" in store.dirs
    assert store.modified == {}


@pytest.mark.asyncio
async def test_process_substitution_is_private_to_its_session():
    ready, release = asyncio.Event(), asyncio.Event()

    async def hold(inv):
        ready.set()
        await release.wait()
        return None, IOResult()

    ws = Workspace({"/data": RAMVFS()}, mode="exec")
    ws.create_session("owner")
    ws.create_session("peer")
    ws.register_cli("hold", CLISpec(name="hold", fn=hold))
    owner = asyncio.create_task(
        ws.shell(
            'consume() { ls /dev/fd >/dev/null; hold; cat "$1"; }; '
            'consume <(echo private)',
            session_id="owner"))
    try:
        await asyncio.wait_for(ready.wait(), timeout=5)
        for command in [
                'cat /dev/fd/63',
                'stat /dev/fd/63',
                'ls /dev/fd',
                'echo corrupt > /dev/fd/63',
                'rm /dev/fd/63',
                'mkdir -p /dev/fd/63',
                'mv /dev/fd /dev/stolen',
        ]:
            result = await ws.shell(command, session_id="peer")
            assert result.exit_code != 0, command
            assert b"private" not in (result.stdout or b"")
        result = await ws.shell('cat <(echo peer)', session_id="peer")
        assert result.stdout == b"peer\n"
        release.set()
        result = await owner
        assert result.exit_code == 0
        assert result.stdout == b"private\n"
        result = await ws.shell('ls /dev', session_id="owner")
        assert b"fd" not in (result.stdout or b"")
    finally:
        release.set()
        await owner
        await ws.close()


@pytest.mark.asyncio
async def test_process_substitution_cleanup_preserves_reused_descriptor():
    old_ready, old_release = asyncio.Event(), asyncio.Event()
    new_ready, new_release = asyncio.Event(), asyncio.Event()

    async def hold_old(inv):
        old_ready.set()
        await old_release.wait()
        return None, IOResult()

    async def hold_new(inv):
        new_ready.set()
        await new_release.wait()
        return None, IOResult()

    ws = Workspace({"/data": RAMVFS()}, mode="exec")
    ws.create_session("owner")
    ws.create_session("peer")
    ws.register_cli("hold-old", CLISpec(name="hold-old", fn=hold_old))
    ws.register_cli("hold-new", CLISpec(name="hold-new", fn=hold_new))
    owner = asyncio.create_task(
        ws.shell(
            'consume() { echo "$1"; rm "$1"; hold-old; }; consume <(echo old)',
            session_id="owner"))
    peer = None
    try:
        await asyncio.wait_for(old_ready.wait(), timeout=5)
        peer = asyncio.create_task(
            ws.shell(
                'consume() { echo "$1"; hold-new; cat "$1"; }; '
                'consume <(echo new)',
                session_id="peer"))
        await asyncio.wait_for(new_ready.wait(), timeout=5)
        old_release.set()
        old_result = await owner
        assert old_result.exit_code == 0
        assert old_result.stdout == b"/dev/fd/63\n"
        new_release.set()
        new_result = await peer
        assert new_result.exit_code == 0
        assert new_result.stdout == b"/dev/fd/63\nnew\n"
        assert (await ws.shell('ls /dev/fd', session_id="peer")).exit_code != 0
    finally:
        old_release.set()
        new_release.set()
        await owner
        if peer is not None:
            await peer
        await ws.close()


def test_stale_allocation_cannot_write_or_release_reused_input():
    dev = DevVFS()
    token = set_current_session(SessionState(session_id="owner"))
    try:
        path, old_allocation = dev.allocate_input()
        del dev._store.files[path[4:]]
        new_path, new_allocation = dev.allocate_input()
        assert new_path == path
        dev.set_input(new_path, new_allocation, b"new")
        dev._store.modified[path[4:]] = "2026-09-23T00:00:00Z"
        dev._store.attrs[path[4:]] = {"mode": 0o600}
        with pytest.raises(FileNotFoundError):
            dev.set_input(path, old_allocation, b"stale")
        dev.release_input(path, old_allocation)
        assert dev._store.files[path[4:]] == b"new"
        assert dev._store.modified[path[4:]] == "2026-09-23T00:00:00Z"
        assert dev._store.attrs[path[4:]] == {"mode": 0o600}
        dev.release_input(new_path, new_allocation)
        dev.release_input(new_path, new_allocation)
        assert path[4:] not in dev._store.files
        assert path[4:] not in dev._store.modified
        assert path[4:] not in dev._store.attrs
    finally:
        reset_current_session(token)
