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

# ruff: noqa: E402

import sys
from pathlib import Path

sys.path[:] = [
    p for p in sys.path if p not in (str(Path(__file__).parent), "")
]

import asyncio
import subprocess
from tempfile import TemporaryDirectory

from mirage import MountMode, Workspace, build_vfs, register_vfs
from mirage.vfs.ram import RAMVFS


class PortableRAM(RAMVFS):
    pass


async def check(ws: Workspace, command: str, stdout: str = "") -> None:
    result = await ws.shell(command)
    assert result.exit_code == 0, (command, await result.stderr_str())
    assert await result.stderr_str() == "", command
    assert await result.stdout_str() == stdout, command


async def write(path: Path) -> None:
    ws = Workspace(
        {
            "/direct/": RAMVFS(),
            "/nested/registered/": build_vfs("portable-ram")
        },
        mode=MountMode.WRITE)
    try:
        await check(ws, "printf 'portable\\n' > /direct/note.txt")
        await check(ws, "printf 'registered\\n' > /nested/registered/note.txt")
        await check(ws, "ln -s /direct/note.txt /nested/registered/link")
        await ws.snapshot(path)
    finally:
        await ws.close()


async def read(path: Path) -> None:
    ws = await Workspace.load(path)
    try:
        await check(ws, "cat /direct/note.txt", "portable\n")
        await check(ws, "cat /nested/registered/*.txt", "registered\n")
        await check(ws, "cat /nested/registered/link", "portable\n")
        registered = next(m.vfs for m in ws.mounts()
                          if m.prefix == "/nested/registered/")
        assert isinstance(registered, PortableRAM)
    finally:
        await ws.close()


async def main() -> None:
    register_vfs("portable-ram", PortableRAM)
    here = Path(__file__).resolve().parent
    command = [
        "pnpm", "--filter", "@struktoai/mirage-integ", "exec", "tsx",
        "snapshot_smoke.ts"
    ]
    with TemporaryDirectory(prefix="mirage-snapshot-smoke-") as folder:
        path = Path(folder) / "state.tar"
        await write(path)
        subprocess.run([*command, "read", str(path)],
                       cwd=here.parent / "typescript",
                       check=True,
                       timeout=60)
        subprocess.run([*command, "write", str(path)],
                       cwd=here.parent / "typescript",
                       check=True,
                       timeout=60)
        await read(path)
    print("Snapshot smoke passed in both directions: "
          "direct and registered mounts")


if __name__ == "__main__":
    asyncio.run(main())
