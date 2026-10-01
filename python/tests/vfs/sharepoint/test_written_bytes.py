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

from mirage.types import MountMode
from mirage.vfs.registry import build_vfs, resolve_class, resolve_entry
from mirage.workspace import Workspace
from tests.fixtures.msgraph_api import (DRIVE_ID, DRIVE_NAME, SITE_NAME,
                                        FakeGraph, serve)


def _ws(graph: FakeGraph) -> Workspace:
    vfs = build_vfs(
        "sharepoint", {
            "access_token": "t",
            "graph_base_url": graph.url,
            "site": SITE_NAME,
            "drive": DRIVE_NAME
        })
    return Workspace({"/m": (vfs, MountMode.WRITE)})


async def _out(ws: Workspace, line: str) -> bytes:
    result = await ws.shell(line)
    out = await result.materialize_stdout()
    err = await result.stderr_str()
    assert (result.exit_code, err) == (0, ""), line
    return out


def _promote(path: str, data: bytes) -> bytes:
    return data + b"<promoted/>" if path.endswith(".docx") else data


def test_keeps_no_written_bytes():
    assert resolve_class(
        resolve_entry("sharepoint").vfs_path).keeps_written_bytes is False


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["a.docx", "a.txt"])
async def test_a_read_after_tee_serves_what_the_library_stored(name):
    # Property promotion rewrites Office files on upload, so the bytes tee
    # wrote are not what the library holds; the next cat downloads them.
    with serve(FakeGraph(drives={DRIVE_ID: {name: b"old\n"}})) as graph:
        graph.on_upload(_promote)
        ws = _ws(graph)
        try:
            await _out(ws, f"echo hi | tee /m/{name}")
            before = graph.fetches()
            assert await _out(ws,
                              f"cat /m/{name}") == graph.data(DRIVE_ID, name)
            assert graph.fetches() - before == 1
        finally:
            await ws.close()
