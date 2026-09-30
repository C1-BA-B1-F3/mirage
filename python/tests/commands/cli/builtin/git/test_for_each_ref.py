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
import json
import os
import shlex
import subprocess
from pathlib import Path

import pytest

from tests.commands.cli.builtin.git.conftest import make_branch, mounted_rw

REFS = Path(__file__).resolve().parents[6] / "integ/fixtures/git/refs.sh"
ENV = {
    **os.environ, "LC_ALL": "C",
    "LANG": "C",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1"
}


@pytest.mark.asyncio
async def test_the_listing_is_sorted_and_formatted(git_ws, repo_path):
    make_branch(repo_path, "feat/git")
    result = await git_ws.shell(
        "git -C /repo for-each-ref --format='%(refname:short) %(objecttype)'"
        " 'refs/*/*'")
    assert result.stdout == b"main commit\n"
    result = await git_ws.shell("git -C /repo for-each-ref --count=1 "
                                "--format='%(refname)%09%(subject)' refs/**")
    assert result.stdout == b"refs/heads/feat/git\tthird\n"


@pytest.mark.asyncio
async def test_an_unknown_atom_is_fatal(git_ws):
    result = await git_ws.shell("git -C /repo for-each-ref --format='%(bogus)'"
                                )
    assert (result.exit_code,
            result.stderr) == (128, b"fatal: unknown field name: bogus\n")


@pytest.fixture(scope="module")
def refs_repo(tmp_path_factory):
    path = tmp_path_factory.mktemp("refs") / "repo"
    subprocess.run(["bash", str(REFS), str(path)],
                   check=True,
                   capture_output=True,
                   env=ENV)
    return path


@pytest.mark.asyncio
@pytest.mark.parametrize("command",
                         json.loads(REFS.with_suffix(".json").read_text()))
async def test_ref_listings_match_git(refs_repo, command):
    native = await asyncio.to_thread(
        subprocess.run,
        ["git", "-C", str(refs_repo), *shlex.split(command)],
        capture_output=True,
        env={
            **ENV, "GIT_TEST_DATE_NOW": "1700000000",
            "TZ": "UTC"
        })
    with mounted_rw(refs_repo) as ws:
        actual = await ws.shell("GIT_TEST_DATE_NOW=1700000000 TZ=UTC "
                                "git -C /repo " + command)
    assert (actual.exit_code, actual.stdout or b"", actual.stderr
            or b"") == (native.returncode, native.stdout, native.stderr)
