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

from mirage.commands.cli.builtin.git.for_each_ref import ref_selected
from tests.commands.cli.builtin.git.conftest import make_branch


@pytest.mark.parametrize("patterns,expected", [
    ((), True),
    (("refs/heads/feat/git", ), True),
    (("refs/heads", ), True),
    (("refs/heads/", ), True),
    (("refs/hea", ), False),
    (("refs/*", ), False),
    (("refs/*/*", ), False),
    (("refs/*/*/*", ), True),
    (("refs/**", ), True),
    (("**/git", ), True),
    (("refs/heads/feat/g?t", ), True),
    (("refs/tags", "refs/heads/*/git"), True),
])
def test_a_pattern_selects_by_prefix_or_path_glob(patterns, expected):
    assert ref_selected("refs/heads/feat/git", patterns) is expected


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
