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

from mirage.types import MountMode
from mirage.vfs.ram import RAMVFS
from mirage.workspace import Workspace


def _ws():
    mem = RAMVFS()
    ws = Workspace(
        {"/data": (mem, MountMode.WRITE)},
        mode=MountMode.WRITE,
    )
    return ws, mem


def _run_raw(ws, cmd, cwd="/", stdin=None):
    ws._cwd = cwd
    io = asyncio.run(ws.shell(cmd, stdin=stdin))
    return io.stdout, io


def _bytes(stdout):
    if isinstance(stdout, bytes):
        return stdout
    return b"".join(asyncio.run(_collect(stdout)))


async def _collect(ait):
    return [chunk async for chunk in ait]


def test_mktemp_creates_file():
    ws, _ = _ws()
    stdout, io = _run_raw(ws, "mktemp")
    path = _bytes(stdout).strip().decode()
    assert path.startswith("/tmp/")
    assert io.exit_code == 0


def test_mktemp_with_dir():
    ws, _ = _ws()
    stdout, io = _run_raw(ws, "mktemp -d")
    path = _bytes(stdout).strip().decode()
    assert path.startswith("/tmp/")
    assert io.exit_code == 0


def test_mktemp_explicit_path_template():
    ws, _ = _ws()
    stdout, io = _run_raw(ws, "mkdir -p /data/mt && mktemp /data/mt/f.XXXX")
    path = _bytes(stdout).strip().decode()
    assert path.startswith("/data/mt/f.")
    assert io.exit_code == 0


def test_mktemp_d_explicit_path_template():
    ws, _ = _ws()
    stdout, io = _run_raw(
        ws, "mkdir -p /data/mtd && mktemp -d /data/mtd/t.XXXX"
    )
    path = _bytes(stdout).strip().decode()
    assert path.startswith("/data/mtd/t.")
    assert io.exit_code == 0


@pytest.mark.parametrize(
    "line,created",
    [
        ("mktemp -u -p /ro", False),
        ("mktemp --dry-run -d -p /ro", False),
        ("mktemp -p /ro", True),
        ("mktemp -d -p /ro", True),
    ],
)
def test_a_read_only_mount_refuses_mktemp_only_where_it_creates(
    line: str, created: bool
):
    # -u only prints the name it would have created, so it runs on a
    # read-only mount; a real create is refused at its write.
    vfs = RAMVFS()
    ws = Workspace({"/ro/": (vfs, MountMode.READ)})
    stdout, io = _run_raw(ws, line)
    if created:
        assert io.exit_code == 1
        assert b"Read-only file system" in (io.stderr or b"")
    else:
        assert io.exit_code == 0
        assert _bytes(stdout).startswith(b"/ro/tmp.")
    assert vfs._store.files == {}


def test_a_pathless_mktemp_creates_under_tmp_whatever_the_cwd():
    # The create goes where /tmp lives (the workspace root), not to the
    # mount the working directory is on, which here is read-only.
    ro = RAMVFS()
    ws = Workspace({"/ro": (ro, MountMode.READ)}, mode=MountMode.WRITE)
    stdout, io = _run_raw(ws, "cd /ro && mktemp && mktemp -d")
    names = _bytes(stdout).decode().split()
    assert io.exit_code == 0
    assert [name.startswith("/tmp/tmp.") for name in names] == [True, True]
    assert ro._store.files == {}


@pytest.mark.parametrize(
    "line,stderr",
    [
        (
            "mktemp -p /data/nodir",
            b"mktemp: failed to create file via template "
            b"'/data/nodir/tmp.XXXXXXXXXX': No such file or directory\n",
        ),
        (
            "mktemp -d --suffix=.s -p /data/nodir x.XXX",
            b"mktemp: failed to create directory via template "
            b"'/data/nodir/x.XXX.s': No such file or directory\n",
        ),
        (
            "cd /data && mktemp sub/x.XXX",
            b"mktemp: failed to create file via template 'sub/x.XXX': "
            b"No such file or directory\n",
        ),
        ("mktemp x.XX", b"mktemp: too few X's in template 'x.XX'\n"),
        (
            "mktemp -p /data /abs/x.XXX",
            b"mktemp: invalid template, '/abs/x.XXX'; with --tmpdir, "
            b"it may not be absolute\n",
        ),
        (
            "mktemp -t sub/x.XXX",
            b"mktemp: invalid template, 'sub/x.XXX', contains directory "
            b"separator\n",
        ),
    ],
)
def test_mktemp_refuses_in_gnu_words(line: str, stderr: bytes):
    # Pinned against GNU coreutils 9.7 (debian:stable-slim); a missing
    # directory is never created.
    ws, mem = _ws()
    _, io = _run_raw(ws, line)
    assert (io.exit_code, io.stderr) == (1, stderr)
    assert mem._store.files == {}


def test_a_bare_template_is_relative_to_the_cwd():
    ws, mem = _ws()
    stdout, io = _run_raw(ws, "cd /data && mktemp x.XXX")
    name = _bytes(stdout).decode().rstrip("\n")
    assert io.exit_code == 0
    assert name.startswith("x.") and len(name) == 5
    assert list(mem._store.files) == ["/" + name]


def test_mktemp_honors_tmpdir():
    ws, mem = _ws()
    stdout, io = _run_raw(
        ws, "TMPDIR=/data mktemp; TMPDIR=/data mktemp -t -p /elsewhere f.XXX"
    )
    names = _bytes(stdout).decode().split()
    assert io.exit_code == 0
    assert [name.startswith(("/data/tmp.", "/data/f.")) for name in names] == [
        True,
        True,
    ]
    assert len(mem._store.files) == 2
