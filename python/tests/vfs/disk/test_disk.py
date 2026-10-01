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
import importlib
import os
from pathlib import Path

import pytest

from mirage import MountMode, Workspace
from mirage.types import ListingVersion, ReadPolicy, ReadSpec
from mirage.vfs.disk import DiskVFS
from mirage.vfs.registry import build_vfs

readdir_module = importlib.import_module("mirage.core.disk.readdir")


@pytest.mark.parametrize(
    "value, shown", [("no", "'no'"), (1, "1"), (None, "None")]
)
def test_folder_versions_must_be_a_boolean(tmp_path, value, shown):
    root = tmp_path / "root"
    with pytest.raises(TypeError) as exc:
        DiskVFS(str(root), folder_versions=value)
    assert str(exc.value) == f"folder_versions must be a boolean, got {shown}"
    assert not root.exists()


def test_folder_versions_default_on(tmp_path):
    vfs = build_vfs("disk", {"root": str(tmp_path)})
    assert vfs.listing_version is ListingVersion.FOLDER
    assert vfs.get_state()["config"] == {
        "root": str(tmp_path.resolve()),
        "folder_versions": True,
    }


def test_the_state_carries_the_knob_turned_off(tmp_path):
    vfs = build_vfs("disk", {"root": str(tmp_path), "folder_versions": False})
    assert vfs.listing_version is ListingVersion.NONE
    assert vfs.get_state()["config"] == {
        "root": str(tmp_path.resolve()),
        "folder_versions": False,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("on, scans_per_command", [(True, 0), (False, 1)])
async def test_the_knob_reaches_the_mount_through_the_config_door(
    tmp_path, monkeypatch, on, scans_per_command
):
    (tmp_path / "a.txt").write_text("a")
    st = os.stat(tmp_path)
    quiet = max(st.st_ctime_ns, st.st_mtime_ns) + 3_000_000_000
    monkeypatch.setattr(
        "mirage.core.disk.listing_version.time_ns", lambda: quiet
    )
    scans: list[Path] = []
    original = readdir_module.read_entries

    def counted(directory):
        scans.append(Path(directory))
        return original(directory)

    monkeypatch.setattr(readdir_module, "read_entries", counted)
    vfs = build_vfs("disk", {"root": str(tmp_path), "folder_versions": on})
    ws = Workspace(
        {"/m": vfs},
        mode=MountMode.WRITE,
        read=ReadSpec(policy=ReadPolicy.FRESH, ttl=600),
    )
    try:
        outputs = []
        for _ in range(3):
            result = await asyncio.wait_for(ws.shell("ls /m"), 10)
            outputs.append(await result.stdout_str())
        assert outputs == ["a.txt\n"] * 3
        assert len(scans) == 1 + 2 * scans_per_command
    finally:
        await ws.close()
