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
import subprocess

import pytest

from mirage.commands.cli.builtin.git.ls_files import pathspec_selects
from tests.commands.cli.builtin.git.conftest import commit_file

ENV = {
    **os.environ, "LC_ALL": "C",
    "LANG": "C",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1"
}


@pytest.mark.parametrize("path,patterns,expected", [
    ("docs/a.md", [""], True),
    ("docs/a.md", ["docs"], True),
    ("docs/a.md", ["doc"], False),
    ("docs/a.md", ["docs/a.md"], True),
    ("docs/sub/a.md", ["*.md"], True),
    ("docs/a.md", ["docs/*.txt", "*.md"], True),
    ("a.txt", ["docs"], False),
])
def test_a_pathspec_names_a_path_a_directory_or_a_glob(path, patterns,
                                                       expected):
    assert pathspec_selects(path, patterns) is expected


@pytest.mark.asyncio
@pytest.mark.parametrize("line", [
    "ls-files",
    "ls-files ..",
    "ls-files '*.txt'",
    "ls-files ../a.txt",
    "ls-files -s ..",
    "ls-files -z",
])
async def test_a_subdirectory_listing_matches_git(git_ws, repo_path, line):
    (repo_path / "docs").mkdir()
    commit_file(repo_path, "docs/note.txt", "note\n", "docs")
    native = await asyncio.to_thread(subprocess.run,
                                     ["bash", "-c", f"cd docs && git {line}"],
                                     cwd=repo_path,
                                     capture_output=True,
                                     env=ENV)
    actual = await git_ws.shell(f"cd /repo/docs && git {line}")
    assert (actual.exit_code, actual.stdout or b"", actual.stderr
            or b"") == (native.returncode, native.stdout, native.stderr)
