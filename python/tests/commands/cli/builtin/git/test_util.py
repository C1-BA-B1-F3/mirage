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

import subprocess

import pytest

from mirage.commands.cli import walk
from mirage.commands.cli.builtin.git import GIT
from mirage.commands.cli.builtin.git.errors import (
    FATAL_EXIT,
    BadConfigValueError,
    NotARepositoryError,
    UnknownSwitchError,
)
from mirage.commands.cli.builtin.git.util import (
    check_operands,
    config_section,
    escaped,
    fatal,
    git_bool,
    start_point,
    switches,
    without_section,
)
from mirage.commands.cli.types import CLIInvocation, CLISpec
from mirage.commands.spec.flag_view import FlagView
from mirage.commands.spec.types import Option


def test_start_point_reads_the_resolved_c_flag():
    assert start_point(FlagView({"C": "/repo/src"})) == "/repo/src"


def test_start_point_falls_back_to_root_without_a_workspace():
    # Only reachable when a leaf is called outside a workspace: inside
    # one the walk always lands the "." default.
    assert start_point(FlagView({})) == "/"


def test_fatal_renders_gits_wording_and_exit():
    stream, io = fatal(NotARepositoryError())
    assert stream is None
    assert io.exit_code == FATAL_EXIT == 128
    assert io.stderr == (
        b"fatal: not a git repository (or any of the "
        b"parent directories): .git\n"
    )


def test_fatal_names_an_explicit_gitdir():
    _stream, io = fatal(NotARepositoryError("/tmp/norepo"))
    assert io.stderr == b"fatal: not a git repository: '/tmp/norepo'\n"


@pytest.mark.asyncio
async def test_an_unsupported_log_flag_says_so_rather_than_blaming_the_repo(
    git_ws,
):
    # Unknown options must not read as missing revisions.
    result = await git_ws.shell("git -C /repo log --zzz")
    assert result.exit_code == 128
    assert result.stderr == b"fatal: unrecognized argument: --zzz\n"


@pytest.mark.asyncio
async def test_an_unsupported_long_log_flag_is_refused_whole(git_ws):
    result = await git_ws.shell("git -C /repo log --simplify-by-decoration")
    assert result.exit_code == 128
    assert result.stderr == (
        b"fatal: unrecognized argument: --simplify-by-decoration\n"
    )


@pytest.mark.asyncio
async def test_an_unsupported_show_flag_is_refused(git_ws):
    result = await git_ws.shell("git -C /repo show --word-diff HEAD")
    assert result.exit_code == 128
    assert result.stderr == b"fatal: unrecognized argument: --word-diff\n"


@pytest.mark.asyncio
async def test_diff_keeps_gits_own_wording_and_exit_for_a_bad_option(git_ws):
    # git words this one differently from log and show, and exits 129
    # rather than 128. Pinned against git 2.50.1.
    result = await git_ws.shell("git -C /repo diff --zzz HEAD")
    assert result.exit_code == 129
    assert result.stderr == b"error: invalid option: --zzz\n"


@pytest.mark.asyncio
async def test_a_refused_flag_costs_no_object_reads(git_ws):
    # The check runs before the repository is opened, so a bad flag is
    # answered without touching the backend.
    result = await git_ws.shell("git -C /nowhere log --zzz")
    assert result.exit_code == 128
    assert result.stderr == b"fatal: unrecognized argument: --zzz\n"


@pytest.mark.asyncio
async def test_a_real_revision_still_resolves(git_ws):
    result = await git_ws.shell("git -C /repo log --oneline HEAD")
    assert result.exit_code == 0
    assert result.stdout


@pytest.mark.asyncio
async def test_an_unknown_revision_keeps_gits_ambiguous_wording(git_ws):
    result = await git_ws.shell("git -C /repo log nosuchref")
    assert result.exit_code == 128
    assert result.stderr.startswith(b"fatal: ambiguous argument 'nosuchref'")


@pytest.mark.asyncio
async def test_status_refuses_an_unknown_option_in_gits_own_words(git_ws):
    # Pinned against git 2.50.1: no program name, the option named
    # without its dashes, backquote-apostrophe quoting, exit 129.
    result = await git_ws.shell("git -C /repo status --nosuch")
    assert result.exit_code == 129
    assert result.stderr == b"error: unknown option `nosuch'\n"


@pytest.mark.asyncio
async def test_a_short_unknown_option_is_a_switch_not_an_option(git_ws):
    result = await git_ws.shell("git -C /repo status -Z")
    assert result.exit_code == 129
    assert result.stderr == b"error: unknown switch `Z'\n"


@pytest.mark.asyncio
async def test_branch_speaks_the_same_dialect(git_ws):
    result = await git_ws.shell("git -C /repo branch -Z")
    assert result.exit_code == 129
    assert result.stderr == b"error: unknown switch `Z'\n"


def test_no_marker_escapes_nothing():
    assert escaped(("rm", "-f", "a.txt")) == frozenset()


def test_the_marker_escapes_every_word_after_it():
    assert escaped(("rm", "--", "-draft", "b.txt")) == {"-draft", "b.txt"}


def test_only_the_first_marker_counts():
    assert escaped(("rm", "--", "-a", "--", "-b")) == {"-a", "--", "-b"}


def test_an_escaped_operand_is_not_a_switch():
    check_operands(("-draft",), UnknownSwitchError, frozenset({"-draft"}))


def test_an_unescaped_dashed_operand_is_still_refused():
    with pytest.raises(UnknownSwitchError):
        check_operands(("-draft",), UnknownSwitchError, frozenset({"-other"}))


# git's parse-options consumes the letters it knows and names the first
# it does not (`git mv -nx` says `x', `git mv -draft` says `d'), so the
# refusal takes the verb's own switches; without them the whole word is
# named, which is how log, show and diff word theirs.
def test_a_cluster_is_refused_at_its_first_unknown_letter():
    with pytest.raises(UnknownSwitchError) as caught:
        check_operands(
            ("-nx",), UnknownSwitchError, frozenset(), frozenset({"n"})
        )
    assert str(caught.value) == "unknown switch `x'"
    with pytest.raises(UnknownSwitchError) as caught:
        check_operands(
            ("-draft",),
            UnknownSwitchError,
            frozenset(),
            frozenset({"f", "k", "n", "v"}),
        )
    assert str(caught.value) == "unknown switch `d'"


def test_a_verb_with_no_switches_still_names_the_first_letter():
    # reset declares none, and git still says `Z' for `git reset -Zq`.
    with pytest.raises(UnknownSwitchError) as caught:
        check_operands(("-Zq",), UnknownSwitchError, frozenset(), frozenset())
    assert str(caught.value) == "unknown switch `Z'"


def test_a_long_option_is_refused_whole():
    with pytest.raises(UnknownSwitchError) as caught:
        check_operands(
            ("--bogus",), UnknownSwitchError, frozenset(), frozenset({"n"})
        )
    assert str(caught.value) == "unknown option `bogus'"


def test_without_known_switches_the_whole_word_is_named():
    with pytest.raises(UnknownSwitchError) as caught:
        check_operands(("-nx",), UnknownSwitchError)
    assert str(caught.value) == "unknown switch `nx'"


async def _verb(inv: CLIInvocation) -> None:
    return None


def test_switches_reads_the_leaf_the_line_was_parsed_against():
    leaf = CLISpec(
        name="mv",
        fn=_verb,
        options=(
            Option(short="-f", long="--force"),
            Option(short="-k"),
            Option(long="--sparse"),
        ),
    )
    assert switches(CLIInvocation(None, spec=leaf)) == {"f", "k"}
    assert switches(CLIInvocation(None)) == frozenset()


@pytest.mark.parametrize(
    "value",
    [
        b"true",
        b"YES",
        b"On",
        b"1",
        b"-1",
        b"+1",
        b"0x10",
        b"010",
        b"2k",
        b"1g",
        b" 1",
        b"-2097152k",
        b"2147483647",
        b"-2147483648",
    ],
)
def test_git_reads_these_as_true(value):
    assert git_bool([value], "core.bare", False) is True


@pytest.mark.parametrize("value", [b"false", b"No", b"OFF", b"", b"0", b"-0"])
def test_git_reads_these_as_false(value):
    assert git_bool([value], "core.bare", True) is False


@pytest.mark.parametrize(
    "value",
    [
        b"maybe",
        b" true",
        b"08",
        b"0x",
        b"1x",
        b"1 ",
        b"- 1",
        b"2g",
        b"2097152k",
        b"2147483648",
        b"-2147483649",
        b"99999999999",
    ],
)
def test_git_cannot_read_these(value):
    # Pinned against git 2.54: strtoimax in base 0, one k, m or g, and a
    # product that has to fit an int.
    with pytest.raises(BadConfigValueError) as excinfo:
        git_bool([value], "core.bare", False)
    assert str(excinfo.value) == (
        f"bad boolean config value '{value.decode()}' for 'core.bare'"
    )


def test_the_last_occurrence_wins():
    assert git_bool([b"true", b"false"], "core.bare", True) is False
    assert git_bool([], "core.bare", True) is True


def test_every_occurrence_is_parsed():
    with pytest.raises(BadConfigValueError):
        git_bool([b"maybe", b"true"], "core.bare", False)


def test_a_later_relative_c_lands_under_the_one_before_it():
    result = walk("git", GIT, ["-C", "/repo", "-C", "docs", "status"], "/")
    assert result.group_flags["-C"] == "/repo/docs"


@pytest.mark.asyncio
async def test_chained_c_runs_the_verb_in_the_composed_directory(
    git_ws, repo_path
):
    (repo_path / "docs").mkdir()
    (repo_path / "docs" / "new.txt").write_text("new\n")
    native = subprocess.run(
        ["git", "-C", str(repo_path), "-C", "docs", "status", "--short"],
        capture_output=True,
    )
    result = await git_ws.shell("git -C /repo -C docs status --short")
    assert (result.exit_code, result.stdout) == (
        native.returncode,
        native.stdout,
    )
    assert result.stdout == b"?? ./\n"


def test_a_config_section_escapes_its_name_and_quotes_comment_values():
    assert config_section(
        "branch",
        'q"x',
        [
            ("remote", "origin"),
            ("merge", "refs/heads/we#rd"),
            ("note", " pad\tend "),
        ],
    ) == (
        '[branch "q\\"x"]\n\tremote = origin\n'
        '\tmerge = "refs/heads/we#rd"\n\tnote = " pad\\tend "\n'
    )


def test_without_section_drops_the_blocks_git_matches_by_name():
    data = (
        b'[core]\n\tbare = false\n[branch "topic"]\n\tremote = o\n'
        b'[branch "main"]\n\tremote = o\n[branch.topic]\n\tmerge = m\n'
        b'  [branch   "topic"] remote = o\n\tmerge = m\n'
        b'[Branch "topic"]\n\tremote = o\n[branch.TOPIC]\n\tremote = o\n'
        b'[branch "q\\"x"]\n\tremote = o\n'
    )
    assert without_section(data, "branch", "topic") == (
        b'[core]\n\tbare = false\n[branch "main"]\n\tremote = o\n'
        b'[Branch "topic"]\n\tremote = o\n[branch.TOPIC]\n\tremote = o\n'
        b'[branch "q\\"x"]\n\tremote = o\n'
    )
    assert without_section(data, "branch", 'q"x').endswith(
        b"[branch.TOPIC]\n\tremote = o\n"
    )


def test_without_section_follows_a_value_continued_onto_a_bracket_line():
    data = (
        b'[core]\n\tbare = false\n[branch "c1"]\n\tdescription = one \\\n'
        b'[two\n\tremote = origin\n[branch "keep"]\n\tremote = origin\n'
        b'[branch "c2"]\n\tdescription = "a\\\n  [b"\n\tremote = origin\n'
        b'[branch "c3"]\n\tnote = x \\\\\n[branch "keep2"]\n\tremote = o\n'
        b'# see \\\n[branch "c4"]\n\tremote = origin\n'
    )
    assert without_section(data, "branch", "c1") == (
        b'[core]\n\tbare = false\n[branch "keep"]\n\tremote = origin\n'
        b'[branch "c2"]\n\tdescription = "a\\\n  [b"\n\tremote = origin\n'
        b'[branch "c3"]\n\tnote = x \\\\\n[branch "keep2"]\n\tremote = o\n'
        b'# see \\\n[branch "c4"]\n\tremote = origin\n'
    )
    assert b'  [b"' not in without_section(data, "branch", "c2")
    assert without_section(data, "branch", "c3").count(b"keep2") == 1
    assert without_section(data, "branch", "c4").endswith(b"# see \\\n")
