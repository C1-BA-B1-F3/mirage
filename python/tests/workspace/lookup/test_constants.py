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

from mirage.types import LsLinkMode, PathSpec
from mirage.workspace.lookup.constants import (
    NO_FOLLOW_COMMANDS,
    dereferences,
    follows_last_component,
    ls_link_mode,
    reads_subtrees,
    walks_mounts,
)


def test_stat_is_a_no_follow_command():
    """GNU stat lstats, so its operands must not be rewritten."""
    assert "stat" in NO_FOLLOW_COMMANDS


def test_bare_dash_l_dereferences():
    assert dereferences("stat", ["stat", "-L", "/data/link"]) is True


def test_clustered_short_flag_dereferences():
    assert dereferences("stat", ["stat", "-Lc", "%n", "/data/link"]) is True


def test_long_form_dereferences():
    assert (
        dereferences("stat", ["stat", "--dereference", "/data/link"]) is True
    )


def test_absent_flag_does_not_dereference():
    assert dereferences("stat", ["stat", "/data/link"]) is False


def test_an_l_inside_a_format_value_does_not_dereference():
    """Only option words count, so `-c '%L'` must not trip the check."""
    assert dereferences("stat", ["stat", "-c", "%L", "/data/link"]) is False


def test_a_command_with_no_dereference_flag_is_never_affected():
    assert dereferences("rm", ["rm", "-L", "/data/link"]) is False


def test_flags_after_end_of_options_are_operands():
    assert dereferences("stat", ["stat", "--", "-L"]) is False


def test_a_pathspec_operand_is_not_read_as_a_flag():
    """Operands arrive classified as PathSpec, not str."""
    spec = PathSpec.from_str_path("/data/-L")
    assert dereferences("stat", ["stat", spec]) is False


@pytest.mark.parametrize(
    "words, mode",
    [
        (["ls", "-l", "/data/link"], LsLinkMode.NONE),
        (["ls", "-d", "/data/link"], LsLinkMode.NONE),
        (["ls", "-la", "/data/link"], LsLinkMode.NONE),
        (["ls", "-g", "/data/link"], LsLinkMode.NONE),
        (["ls", "-F", "/data/link"], LsLinkMode.NONE),
        (["ls", "--cl", "/data/link"], LsLinkMode.NONE),
        (["ls", "--indicator-style=classify", "/data/link"], LsLinkMode.NONE),
        (["ls", "/data/link"], LsLinkMode.DIRECTORY),
        (["ls", "-p", "/data/link"], LsLinkMode.DIRECTORY),
        (["ls", "--file-type", "/data/link"], LsLinkMode.DIRECTORY),
        (["ls", "--classify=never", "/data/link"], LsLinkMode.DIRECTORY),
        (["ls", "-l", "-L", "/data/link"], LsLinkMode.ALL),
        (["ls", "-F", "-H", "/data/link"], LsLinkMode.ALL),
        (
            [
                "ls",
                "-H",
                "--dereference-command-line-symlink-to-dir",
                "/data/link",
            ],
            LsLinkMode.DIRECTORY,
        ),
    ],
)
def test_ls_link_mode_is_gnus_command_line_rule(words, mode):
    # coreutils 9.7: the last of -L, -H and
    # --dereference-command-line-symlink-to-dir wins; without one, -d, a
    # long format or the classify style (abbreviated or valued) resolve
    # no command-line link, and anything else resolves a link to a
    # directory. -p and --file-type are not classify.
    assert ls_link_mode(words) is mode


def test_a_command_with_no_no_follow_flag_is_never_affected():
    # Only ls reads -l as a request to report the link itself.
    assert follows_last_component("cat", ["cat", "-l", "/data/link"]) is True


def test_file_lstats_like_stat():
    """GNU file describes a link; -L is what follows it."""
    assert "file" in NO_FOLLOW_COMMANDS
    assert dereferences("file", ["file", "-L", "/data/link"]) is True


def test_du_does_not_follow_a_link_operand():
    assert "du" in NO_FOLLOW_COMMANDS
    assert dereferences("du", ["du", "-L", "/data/link"]) is True


def test_find_link_options_are_last_wins():
    # GNU takes the last of -P/-H/-L: `find -L -P x` does not follow,
    # `find -P -L x` does.
    assert dereferences("find", ["find", "-L", "-P", "/data/link"]) is False
    assert dereferences("find", ["find", "-P", "-L", "/data/link"]) is True
    assert (
        dereferences("find", ["find", "-L", "-P", "-L", "/data/link"]) is True
    )
    assert dereferences("find", ["find", "-H", "/data/link"]) is True
    assert dereferences("find", ["find", "/data/link"]) is False


def test_find_link_options_only_count_before_the_operand():
    # -L after the start point is a predicate position, not a policy one.
    assert dereferences("find", ["find", "/data/link", "-L"]) is False


def test_walkers_are_read_off_the_raw_line():
    # find/du/tree/rg always descend; grep and ls only under a flag,
    # read raw because admission fires before flag parsing.
    assert walks_mounts("find", ["find", "/data"]) is True
    assert walks_mounts("du", ["du", "/data"]) is True
    assert walks_mounts("tree", ["tree"]) is True
    assert walks_mounts("rg", ["rg", "x"]) is True
    assert walks_mounts("grep", ["grep", "x", "/data"]) is False
    assert walks_mounts("grep", ["grep", "-rn", "x", "/data"]) is True
    assert walks_mounts("grep", ["grep", "--recursive", "x"]) is True
    assert walks_mounts("grep", ["grep", "--", "-r"]) is False
    assert walks_mounts("ls", ["ls", "-R", "/data"]) is True
    assert walks_mounts("ls", ["ls", "-l", "/data"]) is False
    assert walks_mounts("cat", ["cat", "/data/x"]) is False


def test_subtree_readers_cover_the_archivers_and_recursive_copy():
    # tar -c and zip -r and cp -r read below their operands but stop at
    # a mount boundary, so they read subtrees without walking mounts.
    assert reads_subtrees("tar", ["tar", "-cf", "/out.tar", "/data"]) is True
    assert reads_subtrees("tar", ["tar", "-xf", "/out.tar"]) is False
    assert reads_subtrees("zip", ["zip", "-r", "/out.zip", "/data"]) is True
    assert reads_subtrees("cp", ["cp", "-r", "/data", "/copy"]) is True
    assert reads_subtrees("cp", ["cp", "/data/a", "/copy"]) is False
    assert reads_subtrees("grep", ["grep", "-r", "x", "/data"]) is True
    assert walks_mounts("tar", ["tar", "-cf", "/out.tar", "/data"]) is False
