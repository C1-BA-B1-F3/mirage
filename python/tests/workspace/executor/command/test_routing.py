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

from mirage.commands.cli.specs import cli_spec_for
from mirage.io.types import DeviceInput
from mirage.types import MountMode, PathSpec
from mirage.vfs.ram import RAMVFS
from mirage.workspace import Workspace
from mirage.workspace.executor.command.routing import (default_cwd_operand,
                                                       merge_scopes,
                                                       path_flag_scopes,
                                                       program_tokens)


def _path(virtual: str) -> PathSpec:
    return PathSpec(virtual=virtual,
                    directory=virtual,
                    vfs_path="",
                    resolved=True)


def test_merge_scopes_keeps_operand_order_and_dedupes():
    a, b = _path("/m/a"), _path("/m/b")
    dup = _path("/m/a")
    merged = merge_scopes([a, b], [dup, _path("/m/c")])
    assert [p.virtual for p in merged] == ["/m/a", "/m/b", "/m/c"]


def test_path_flag_scopes_reads_path_valued_flags():
    scopes = path_flag_scopes("shuf", ["--output=/dst/out", "/src/in"], "/")
    assert [s.virtual for s in scopes] == ["/dst/out"]


def test_path_flag_scopes_unknown_command_is_empty():
    assert path_flag_scopes("nosuchcmd", ["-x", "/a"], "/") == []


@pytest.mark.parametrize("cmd, flag", [("grep", "-f"), ("rg", "-f"),
                                       ("zgrep", "-f"), ("sed", "-f"),
                                       ("awk", "-f"), ("jq", "--from-file")])
def test_path_flag_scopes_leaves_a_program_file_out(cmd: str, flag: str):
    # The program file is read before routing, so a pattern file on
    # another mount does not make the line cross-mount, for every command
    # that reads one: the keys come from the reader's own table.
    assert path_flag_scopes(cmd, [flag, "/other/p", "/data/in"], "/") == []


@pytest.mark.parametrize("cmd, argv", [
    ("curl", ["-o", "/other/body", "-D", "/data/h", "http://x.test/"]),
    ("curl",
     ["--dump-header", "-", "--output", "/other/body", "http://x.test/"]),
    ("jq", [
        "--slurpfile", "s", "/other/s.json", "--rawfile", "r", "/dev/fd/63",
        "."
    ]),
])
def test_path_flag_scopes_leaves_door_files_out(cmd: str, argv: list[str]):
    # The handler reaches them through the dispatcher, so they name no
    # mount the line has to run on (DOOR_FLAG_KEYS).
    assert path_flag_scopes(cmd, argv, "/") == []


def test_program_tokens_walks_a_cli_verb_path_and_keeps_the_rest_raw():
    ws = Workspace(mounts={"/ram": (RAMVFS(), MountMode.WRITE)})
    try:
        ws.register_cli("git", cli_spec_for("git"))
        reg = ws._registry
        # Options before the verb are not the verb; an alias reads as
        # its canonical name; the leaf's own words follow untouched.
        assert program_tokens(reg, "git",
                              ["-C", "/r", "reset", "--hard", "HEAD"],
                              "/") == (("git", "reset", "--hard", "HEAD"),
                                       ("git", "reset"))
        assert program_tokens(reg, "git", ["log", "-1"],
                              "/") == (("git", "log", "-1"), ("git", "log"))
        # A walk the tree refuses (unknown verb, bare head) reads raw.
        assert program_tokens(reg, "git", ["frobnicate", "x"],
                              "/") == (("git", "frobnicate", "x"), ("git", ))
        assert program_tokens(reg, "git", [], "/") == (("git", ), ("git", ))
        # Anything else is the name and the raw argv.
        assert program_tokens(reg, "rm", ["-rf", "/x"],
                              "/") == (("rm", "-rf", "/x"), ("rm", ))
    finally:
        import asyncio
        asyncio.run(ws.close())


@pytest.mark.asyncio
async def test_rg_searches_the_cwd_once_dash_f_takes_stdin():
    # ripgrep 14.1.1: an attached stdin wins over the cwd, but `-f -`
    # reads it for patterns first, which leaves only the cwd to search.
    # The `-` arrives classified, so its spelling is what says stdin.
    ws = Workspace(mounts={"/ram": (RAMVFS(), MountMode.WRITE)})
    try:
        reg = ws._registry
        dash = PathSpec(virtual="/ram/-",
                        directory="/ram/",
                        vfs_path="",
                        resolved=True,
                        raw_path="-")
        operand = default_cwd_operand(["rg", "-f", dash], "rg", reg, "/ram",
                                      b"a\n")
        assert operand is not None and operand.raw_path == ""
        assert default_cwd_operand(["rg", "-f", _path("/ram/p")], "rg", reg,
                                   "/ram", b"a\n") is None
        assert default_cwd_operand(["rg", "a"], "rg", reg, "/ram",
                                   b"a\n") is None
    finally:
        await ws.close()


@pytest.mark.asyncio
async def test_rg_searches_the_cwd_when_stdin_is_a_device():
    # ripgrep 14.1.1 searches stdin only when a file, FIFO or socket is
    # attached (grep_cli::is_readable_stdin): `rg a < /dev/null` searches
    # the cwd, while an empty file or pipe is still searched.
    ws = Workspace(mounts={"/ram": (RAMVFS(), MountMode.WRITE)})
    try:
        reg = ws._registry
        operand = default_cwd_operand(["rg", "a"], "rg", reg, "/ram",
                                      DeviceInput())
        assert operand is not None and operand.raw_path == ""
        assert default_cwd_operand(["rg", "a"], "rg", reg, "/ram", b"") is None
    finally:
        await ws.close()
