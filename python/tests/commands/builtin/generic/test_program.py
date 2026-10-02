import pytest

from mirage.commands.builtin.generic.program import (
    prepare_program,
    program_file_refusal,
    read_program_file,
)
from mirage.io.types import IOResult, materialize
from mirage.types import FileStat, FileType, PathSpec


def _typed(raw: str) -> PathSpec:
    virtual = raw if raw.startswith("/") else "/" + raw
    return PathSpec(
        virtual=virtual,
        directory="/",
        vfs_path="",
        resolved=True,
        raw_path=raw,
    )


async def _no_dispatch(op, path):
    raise AssertionError(f"stdin only, but {op} {path} was dispatched")


@pytest.mark.asyncio
async def test_rg_pattern_file_from_stdin_lowers_to_regexp():
    texts, flags, rest, error = await prepare_program(
        "rg", ["/in"], {"file": [_typed("-")]}, b"a\nb\n", _no_dispatch
    )
    assert error is None
    assert (texts, flags) == (["/in"], {"file": [], "regexp": ["a\nb"]})
    assert await materialize(rest) == b""


@pytest.mark.asyncio
async def test_rg_dev_stdin_pattern_file_takes_no_dash():
    # ripgrep reads `-f /dev/stdin` as a file, so a `-` operand after it
    # searches what is left of stdin (nothing) rather than being refused.
    _, flags, rest, error = await prepare_program(
        "rg",
        [],
        {"file": [_typed("/dev/stdin")]},
        b"a\n",
        _no_dispatch,
        [_typed("-")],
    )
    assert error is None
    assert flags == {"file": [], "regexp": ["a"]}
    assert await materialize(rest) == b""


@pytest.mark.asyncio
async def test_grep_reads_a_dash_pattern_file_twice_without_refusing():
    # GNU grep 3.11 reads the second `-f -` as an empty pattern file.
    _, flags, _, error = await prepare_program(
        "grep",
        [],
        {"file": [_typed("-"), _typed("-")], "e": []},
        b"a\n",
        _no_dispatch,
        [_typed("-")],
    )
    assert error is None
    assert flags == {"file": [], "e": ["a"]}


@pytest.mark.parametrize(
    "name,exc,line,code",
    [
        ("grep", IsADirectoryError(), "grep: dir: Is a directory\n", 2),
        (
            "grep",
            FileNotFoundError(),
            "grep: dir: No such file or directory\n",
            2,
        ),
        (
            "rg",
            IsADirectoryError(),
            "rg: dir:Is a directory (os error 21)\n",
            2,
        ),
        (
            "rg",
            FileNotFoundError(),
            "rg: dir: No such file or directory (os error 2)\n",
            2,
        ),
        (
            "rg",
            NotADirectoryError(),
            "rg: dir: Not a directory (os error 20)\n",
            2,
        ),
        ("zgrep", IsADirectoryError(), "cat: dir: Is a directory\n", 2),
        (
            "zgrep",
            FileNotFoundError(),
            "cat: dir: No such file or directory\n",
            2,
        ),
        (
            "sed",
            FileNotFoundError(),
            "sed: couldn't open file dir: No such file or directory\n",
            4,
        ),
        ("awk", IsADirectoryError(), "awk: read error (Is a directory)\n", 2),
        (
            "awk",
            FileNotFoundError(),
            'awk: cannot open "dir" (No such file or directory)\n',
            2,
        ),
        (
            "jq",
            IsADirectoryError(),
            "jq: Could not open dir: It's a directory\n",
            2,
        ),
        (
            "jq",
            FileNotFoundError(),
            "jq: Could not open dir: No such file or directory\n",
            2,
        ),
    ],
)
def test_a_program_file_refusal_is_in_each_commands_words(
    name, exc, line, code
):
    # grep 3.11, ripgrep 14.1.1, gzip 1.13 (zgrep copies the file with
    # cat), sed 4.9, mawk 1.3.4, jq 1.7.1 on debian:stable-slim.
    assert program_file_refusal(name, _typed("dir"), exc) == (line, code)


@pytest.mark.asyncio
@pytest.mark.parametrize("name,data", [("sed", b""), ("grep", None)])
async def test_a_directory_program_file_is_read_as_the_command_reads_it(
    name, data
):
    # sed 4.9 reads a directory as an empty script; everyone else fails
    # its read, which the stat tells from a keyed store's plain miss.

    async def dispatch(op, path, **kwargs):
        assert op == "stat", f"{op} {path.virtual} was dispatched"
        return FileStat(name="dir", type=FileType.DIRECTORY), IOResult()

    if data is None:
        with pytest.raises(IsADirectoryError):
            await read_program_file(name, _typed("dir"), dispatch)
    else:
        assert await read_program_file(name, _typed("dir"), dispatch) == data
