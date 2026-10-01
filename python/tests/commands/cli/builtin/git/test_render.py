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

from mirage.commands.cli.builtin.git.render import (
    branch_line,
    long_format,
    quote_path,
    relative_entries,
    short_format,
    short_line,
    tracking_lines,
)
from mirage.commands.cli.builtin.git.types import StatusEntry, Upstream


def row(path: str, index: str, tree: str, original: str | None = None):
    """One status row.

    Args:
        path (str): repository-relative path.
        index (str): the left column.
        tree (str): the right column.
        original (str | None): the renamed-from path.
    """
    return StatusEntry(path, index, tree, original)


# Each row is (path, whether the machine formats quote it, whether the
# human one does). Pinned against git 2.47: a space forces quoting only
# where the output is meant to be split on whitespace.
QUOTING = [
    ("plain.txt", "plain.txt", "plain.txt"),
    ("has space.txt", '"has space.txt"', "has space.txt"),
    ('quo"te.txt', '"quo\\"te.txt"', '"quo\\"te.txt"'),
    ("back\\slash.txt", '"back\\\\slash.txt"', '"back\\\\slash.txt"'),
    ("héllo.txt", '"h\\303\\251llo.txt"', '"h\\303\\251llo.txt"'),
    ("tab\there.txt", '"tab\\there.txt"', '"tab\\there.txt"'),
]


@pytest.mark.parametrize("path,machine,human", QUOTING)
def test_quoting_matches_git(path, machine, human):
    assert quote_path(path, True) == machine
    assert quote_path(path, False) == human


def test_a_short_line_is_two_columns_then_the_path():
    assert short_line(row("a.txt", "M", " ")) == "M  a.txt"


def test_a_rename_names_both_sides():
    assert (
        short_line(row("new.txt", "R", " ", "old.txt"))
        == "R  old.txt -> new.txt"
    )


def test_the_branch_line_is_absent_without_the_flag():
    assert short_format([row("a.txt", "?", "?")], None) == "?? a.txt\n"


def test_the_branch_line_leads_when_asked():
    header = branch_line("main", False)
    assert short_format([], header) == "## main\n"


def test_an_unborn_branch_says_so():
    assert branch_line("main", True) == "## No commits yet on main"


def test_a_detached_head_has_no_branch_to_name():
    assert branch_line(None, False) == "## HEAD (no branch)"


def test_a_clean_tree_is_two_lines():
    assert long_format([], "main", "", False, False, False) == (
        "On branch main\nnothing to commit, working tree clean\n"
    )


def test_an_unborn_repository_announces_it_before_anything_else():
    body = long_format([], "main", "", True, False, False)
    assert body.splitlines()[:3] == ["On branch main", "", "No commits yet"]


def test_the_unborn_repository_offers_a_different_unstage_hint():
    # `git restore --staged` has nothing to restore to before the first
    # commit, so git names `git rm --cached` instead.
    body = long_format(
        [row("a.txt", "A", " ")], "main", "", True, False, False
    )
    assert '(use "git rm --cached <file>..." to unstage)' in body


def test_a_merge_in_progress_drops_the_unstage_hint():
    body = long_format(
        [row("a.txt", "M", " ")], "main", "", False, True, False
    )
    assert "to unstage" not in body
    assert "All conflicts fixed but you are still merging." in body


def test_an_unresolved_merge_says_which_conflicts_remain():
    body = long_format(
        [row("f.txt", "U", "U")], "main", "", False, True, False
    )
    assert "You have unmerged paths." in body
    assert "\tboth modified:   f.txt" in body


def test_every_conflict_shape_has_its_own_label():
    labels = {
        ("D", "D"): "both deleted:",
        ("A", "U"): "added by us:",
        ("U", "D"): "deleted by them:",
        ("U", "A"): "added by them:",
        ("D", "U"): "deleted by us:",
        ("A", "A"): "both added:",
        ("U", "U"): "both modified:",
    }
    for (index, tree), label in labels.items():
        body = long_format(
            [row("f.txt", index, tree)], "main", "", False, True, False
        )
        assert f"\t{label:<17}f.txt" in body


def test_a_staged_change_silences_the_trailer():
    body = long_format(
        [row("a.txt", "M", " ")], "main", "", False, False, False
    )
    assert "nothing to commit" not in body
    assert "no changes added" not in body


def test_untracked_alone_says_nothing_was_added():
    body = long_format(
        [row("a.txt", "?", "?")], "main", "", False, False, False
    )
    assert body.endswith(
        "nothing added to commit but untracked files "
        'present (use "git add" to track)\n'
    )


def test_hiding_untracked_changes_the_clean_line_rather_than_adding_one():
    body = long_format([], "main", "", False, False, True)
    assert body == (
        "On branch main\nnothing to commit (use -u to show untracked files)\n"
    )


def test_hiding_untracked_notes_the_omission_when_something_is_staged():
    body = long_format(
        [row("a.txt", "M", " ")], "main", "", False, False, True
    )
    assert body.endswith(
        "Untracked files not listed (use -u option to show untracked files)\n"
    )


def test_the_two_sections_can_name_the_same_path():
    body = long_format(
        [row("a.txt", "M", "M")], "main", "", False, False, False
    )
    assert body.count("\tmodified:   a.txt") == 2


# Pinned against git 2.50 with core.quotePath=false: a byte outside
# ASCII passes through, and everything git quotes anyway still is.
UNQUOTED = [
    ("héllo.txt", "héllo.txt"),
    ("tab\thé.txt", '"tab\\thé.txt"'),
    ("del\x7f.txt", '"del\\177.txt"'),
    ("\udcff.txt", "\udcff.txt"),
]


@pytest.mark.parametrize("path,human", UNQUOTED)
def test_quote_path_off_leaves_non_ascii_alone(path, human):
    assert quote_path(path, False, False) == human


def test_an_undecodable_byte_is_quoted_as_itself():
    assert quote_path("\udcff.txt", False) == '"\\377.txt"'


@pytest.mark.parametrize(
    "prefix, path, shown",
    [
        # Pinned against git 2.54 from inside each directory.
        ("docs", "letters.txt", "../letters.txt"),
        ("docs", "docs/extra.md", "extra.md"),
        ("docs", "docs2/x", "../docs2/x"),
        ("new", "new/", "./"),
        ("new/deep", "new/", "../"),
        ("new/deep", "new/deep/f.txt", "f.txt"),
    ],
)
def test_rows_read_from_the_invocation_directory(prefix, path, shown):
    assert relative_entries([row(path, "?", "?")], prefix)[0].path == shown


def test_a_rename_shows_both_sides_from_the_invocation_directory():
    moved = relative_entries(
        [row("docs/numbers.txt", "R", " ", "numbers.txt")], "docs"
    )[0]
    assert (moved.original, moved.path) == ("../numbers.txt", "numbers.txt")


def test_rows_stay_repository_relative_at_the_top():
    rows = [row("docs/readme.md", " ", "M")]
    assert relative_entries(rows, "") is rows


@pytest.mark.parametrize(
    "ahead,behind,gone,expected",
    [
        (0, 0, False, ["Your branch is up to date with 'origin/main'."]),
        (
            1,
            0,
            False,
            [
                "Your branch is ahead of 'origin/main' by 1 commit.",
                '  (use "git push" to publish your local commits)',
            ],
        ),
        (
            0,
            2,
            False,
            [
                "Your branch is behind 'origin/main' by 2 commits, and can be "
                "fast-forwarded.",
                '  (use "git pull" to update your local branch)',
            ],
        ),
        (
            1,
            1,
            False,
            [
                "Your branch and 'origin/main' have diverged,",
                "and have 1 and 1 different commits each, respectively.",
                '  (use "git pull" if you want to integrate the remote branch with '
                "yours)",
            ],
        ),
        (
            0,
            0,
            True,
            [
                "Your branch is based on 'origin/main', but the upstream is gone.",
                '  (use "git branch --unset-upstream" to fixup)',
            ],
        ),
    ],
)
def test_tracking_lines_read_as_git_writes_them(ahead, behind, gone, expected):
    assert (
        tracking_lines(Upstream("origin/main", ahead, behind, gone))
        == expected
    )


@pytest.mark.parametrize(
    "upstream,expected",
    [
        (Upstream("origin/main", 0, 0, False), "## main...origin/main"),
        (
            Upstream("origin/main", 1, 2, False),
            "## main...origin/main [ahead 1, behind 2]",
        ),
        (Upstream("origin/gone", 0, 0, True), "## main...origin/gone [gone]"),
    ],
)
def test_the_branch_line_names_the_upstream(upstream, expected):
    assert branch_line("main", False, upstream) == expected
