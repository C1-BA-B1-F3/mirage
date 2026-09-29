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

from dataclasses import dataclass, field

from mirage.commands.cli.builtin.git.graph import CommitGraph


@dataclass
class _Commit:
    id: bytes
    parents: list[bytes] = field(default_factory=list)


def _commit(sha: str, *parents: str) -> _Commit:
    return _Commit(sha.encode(), [p.encode() for p in parents])


def _drawn(commits: list[_Commit], first_parent: bool = False) -> list[str]:
    """The graph lines ``--oneline`` prints, one commit per call.

    Args:
        commits (list[_Commit]): the commits in walk order.
        first_parent (bool): ``--first-parent``.
    """
    shown = {commit.id for commit in commits}
    graph = CommitGraph(shown.__contains__, first_parent)
    lines: list[str] = []
    for commit in commits:
        graph.update(commit)
        text = (graph.show_commit() + commit.id.decode() +
                graph.show_message(""))
        lines.extend(text.split("\n"))
    return lines


# The issue's history, pinned against git 2.50.1: a merge whose second
# parent's line is drawn first, then collapses back into the first.
def test_draws_a_merge_and_collapses_its_branch_line():
    history = [
        _commit("M", "C", "B"),
        _commit("B", "A"),
        _commit("C", "A"),
        _commit("A"),
    ]
    assert _drawn(history) == [
        "*   M",
        "|\\  ",
        "| * B",
        "* | C",
        "|/  ",
        "* A",
    ]


def test_widens_the_space_around_an_octopus_with_a_column_to_its_right():
    history = [
        _commit("T", "Z"),
        _commit("O", "A", "B", "C"),
        _commit("C", "Z"),
        _commit("B", "Z"),
        _commit("A", "Z"),
        _commit("Z"),
    ]
    assert _drawn(history) == [
        "* T",
        "| *-.   O",
        "| |\\ \\  ",
        "| | | * C",
        "| |_|/  ",
        "|/| |   ",
        "| | * B",
        "| |/  ",
        "|/|   ",
        "| * A",
        "|/  ",
        "* Z",
    ]


def test_draws_a_parent_the_walk_does_not_show_as_no_line_at_all():
    graph = CommitGraph(lambda sha: sha != b"X", False)
    graph.update(_commit("M", "A", "X"))
    assert graph.show_commit() == "* "
    assert graph.is_finished()


def test_draws_a_merge_as_one_line_under_first_parent():
    assert _drawn(
        [_commit("M", "A", "B"), _commit("A")],
        first_parent=True) == ["* M", "* A"]


def test_marks_a_commit_whose_predecessor_never_finished_with_an_ellipsis():
    graph = CommitGraph(lambda sha: True, False)
    graph.update(_commit("M", "A", "B"))
    graph.update(_commit("B", "A"))
    assert graph.show_commit() == "... \n| * "
