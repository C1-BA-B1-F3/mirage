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
import sys
import tempfile

from mirage import MountMode, Workspace
from mirage.config import load_config
from mirage.vfs.disk import DiskVFS
from mirage.vfs.ram import RAMVFS
from mirage.workspace.mount import MountEntry

_fail = 0


def check(label: str, cond: bool) -> None:
    global _fail
    if cond:
        print(f"OK   {label}")
    else:
        _fail += 1
        print(f"FAIL {label}")


async def _out(ws: Workspace, cmd: str, stdin: bytes | None = None) -> str:
    res = await ws.shell(cmd, stdin=stdin)
    return await res.stdout_str()


def _root(ws: Workspace) -> MountEntry | None:
    return next((m for m in ws.mounts() if m.prefix == "/"), None)


async def default_root_is_ram() -> None:
    ws = Workspace({"/data/": RAMVFS()}, mode=MountMode.WRITE)
    root = _root(ws)
    check("default: root is a normal mount entry at /", root is not None)
    check(
        "default: root backed by ram",
        root is not None and isinstance(root.vfs, RAMVFS),
    )
    ls = await _out(ws, "ls /")
    check("default: ls / lists child mounts", "data" in ls and "dev" in ls)
    check("default: ls / hides dotfile mounts", ".bash_history" not in ls)
    await ws.shell("echo scratch > /note.txt")
    check(
        "default: write to unmounted / lands on root scratch",
        (await _out(ws, "cat /note.txt")).strip() == "scratch",
    )
    wc = await _out(ws, "wc -c", stdin=b"abcd")
    check("default: arg-less command resolves at root", wc.strip() == "4")
    await ws.close()


async def ram_root_override() -> None:
    ws = Workspace({"/": RAMVFS(), "/sub/": RAMVFS()}, mode=MountMode.WRITE)
    check(
        "ram-root: / is the user mount (not duplicated)",
        len([m for m in ws.mounts() if m.prefix == "/"]) == 1,
    )
    await ws.shell("echo hi > /top.txt")
    await ws.shell("echo deep > /sub/inner.txt")
    check(
        "ram-root: read file written at root",
        (await _out(ws, "cat /top.txt")).strip() == "hi",
    )
    ls = await _out(ws, "ls /")
    check(
        "ram-root: ls / shows root file and child mount",
        "top.txt" in ls and "sub" in ls,
    )
    check(
        "ram-root: read through child mount",
        (await _out(ws, "cat /sub/inner.txt")).strip() == "deep",
    )
    await ws.close()


async def disk_root_override() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        ws = Workspace({"/": DiskVFS(root=tmp)}, mode=MountMode.WRITE)
        root = _root(ws)
        check(
            "disk-root: root backed by disk",
            root is not None and isinstance(root.vfs, DiskVFS),
        )
        await ws.shell("echo persisted > /file.txt")
        check(
            "disk-root: read file back through root",
            (await _out(ws, "cat /file.txt")).strip() == "persisted",
        )
        on_disk = os.path.join(tmp, "file.txt")
        check(
            "disk-root: write at / persisted to the real disk path",
            os.path.exists(on_disk),
        )
        if os.path.exists(on_disk):
            with open(on_disk) as f:
                check(
                    "disk-root: on-disk content matches",
                    f.read().strip() == "persisted",
                )
        await ws.close()


async def yaml_controls_root() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = load_config(
            {"mounts": {"/": {"vfs": "disk", "config": {"root": tmp}}}}
        )
        kwargs = cfg.to_workspace_kwargs()
        check("yaml: '/' mount present in mounts", "/" in kwargs["mounts"])
        ws = Workspace(**kwargs)
        root = _root(ws)
        check(
            "yaml: root overridden to disk via config",
            root is not None and isinstance(root.vfs, DiskVFS),
        )
        await ws.shell("echo fromyaml > /y.txt")
        check(
            "yaml: write at / persisted to disk",
            os.path.exists(os.path.join(tmp, "y.txt")),
        )
        await ws.close()

    ws = Workspace(
        **load_config(
            {"mounts": {"/data": {"vfs": "ram"}}}
        ).to_workspace_kwargs()
    )
    root = _root(ws)
    check(
        "yaml: no '/' mount falls back to ram root",
        root is not None and isinstance(root.vfs, RAMVFS),
    )
    await ws.close()


async def main() -> None:
    await default_root_is_ram()
    await ram_root_override()
    await disk_root_override()
    await yaml_controls_root()
    if _fail:
        print(f"\n{_fail} check(s) failed")
        sys.exit(1)
    print("\nroot mount OK")


if __name__ == "__main__":
    asyncio.run(main())
