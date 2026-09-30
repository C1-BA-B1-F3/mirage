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

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from mirage.commands.cli.builtin.git import GIT
from mirage.commands.cli.builtin.git.fetch import (Row, Wanted, ignore_funny,
                                                   prettify, summary_lines)
from mirage.types import MountMode
from mirage.vfs.disk import DiskVFS
from mirage.workspace import Workspace

SCENARIO = Path(__file__).resolve().parents[6] / "integ/fixtures/git/remote.sh"
ENV = {
    **os.environ, "LC_ALL": "C",
    "LANG": "C",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "A",
    "GIT_AUTHOR_EMAIL": "a@example.com",
    "GIT_COMMITTER_NAME": "A",
    "GIT_COMMITTER_EMAIL": "a@example.com",
    "GIT_AUTHOR_DATE": "2024-01-01T00:00:00Z",
    "GIT_COMMITTER_DATE": "2024-01-01T00:00:00Z"
}
# macOS git writes these two into every new repository's config.
HOST_ONLY = b"\tignorecase = true\n\tprecomposeunicode = true\n"


def test_a_ref_git_refuses_to_name_locally_is_dropped_with_its_error():
    oid = "a" * 40
    wanted = [
        Wanted("refs/heads/main", oid, "refs/remotes/o/main"),
        Wanted("refs/tags/../../x", oid, "refs/tags/../../x"),
        Wanted("refs/heads/main", oid, "HEAD"),
        Wanted("HEAD", oid, None),
    ]
    kept, notes = ignore_funny(wanted)
    assert kept == [wanted[0], wanted[3]]
    assert notes == ("error: * Ignoring funny ref 'refs/tags/../../x' "
                     "locally\nerror: * Ignoring funny ref 'HEAD' locally\n")


def test_prettify_strips_the_three_namespaces():
    assert [
        prettify(r)
        for r in ("refs/heads/a", "refs/tags/b", "refs/remotes/o/c", "HEAD")
    ] == ["a", "b", "o/c", "HEAD"]


def test_the_summary_columns_widen_for_a_long_ref():
    rows = [
        Row("*", "[new branch]", "a-very-long-branch-name", "o/x", "", True),
        Row(" ", "1234567..89abcde", "main", "o/main", "", True),
    ]
    assert summary_lines(
        "/w/src.git/", rows,
        7) == ("From /w/src\n"
               " * [new branch]      a-very-long-branch-name -> o/x\n"
               "   1234567..89abcde  main                    -> o/main\n")


@pytest.fixture(scope="module")
def scenario(tmp_path_factory):
    base = tmp_path_factory.mktemp("remote")
    native, ours = base / "native", base / "mirage"
    subprocess.run(["bash", str(SCENARIO), str(native)],
                   check=True,
                   capture_output=True,
                   env=ENV)
    shutil.copytree(native, ours, symlinks=True)
    return native, ours


def _native(root: Path, line: str) -> tuple[int, bytes, bytes]:
    done = subprocess.run(["bash", "-c", line],
                          cwd=root,
                          capture_output=True,
                          env=ENV)
    spelled = [str(root.resolve()).encode(), str(root).encode()]

    def local(data: bytes) -> bytes:
        for path in spelled:
            data = data.replace(path, b"/w")
        return data.replace(HOST_ONLY, b"")

    return done.returncode, local(done.stdout), local(done.stderr)


@pytest.mark.asyncio
async def test_clone_and_fetch_between_workspace_repositories_match_git(
        scenario):
    native, ours = scenario
    steps = json.loads(SCENARIO.with_suffix(".json").read_text())
    for step in steps:
        if step.startswith("!"):
            for root in (native, ours):
                subprocess.run(["bash", "-ec", step[1:]],
                               cwd=root,
                               check=True,
                               capture_output=True,
                               env=ENV)
            continue
        with Workspace({"/w/": DiskVFS(root=str(ours))},
                       mode=MountMode.WRITE) as ws:
            ws.register_cli("git", GIT)
            result = await ws.shell(f"cd /w && {step}")
        actual = (result.exit_code, result.stdout or b"", result.stderr or b"")
        assert actual == _native(native, step), step
