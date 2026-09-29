from collections.abc import Awaitable, Callable

import pytest

from mirage.commands.builtin.errors import SortKeyError
from mirage.commands.builtin.generic.sort import parse_flags, sort
from mirage.commands.errors import UsageError
from mirage.commands.spec import SPECS, parse_command, parse_to_kwargs
from mirage.io.types import IOResult, materialize
from mirage.shell.descriptors import unreadable_stdin
from mirage.types import PathSpec


async def _unused_read_bytes(_path: PathSpec) -> bytes:
    raise AssertionError("read_bytes should not be called")


@pytest.mark.asyncio
async def test_no_operand_uses_empty_standard_input():
    stdout, io = await sort([], read_bytes=_unused_read_bytes)

    assert await materialize(stdout) == b""
    assert io.exit_code == 0


@pytest.mark.asyncio
async def test_zero_field_keydef_exits_two():
    stdout, io = await sort([],
                            read_bytes=_unused_read_bytes,
                            stdin=b"a\nb\n",
                            key_defs=["0"])

    assert await materialize(stdout) == b""
    assert io.exit_code == 2
    assert b"field number is zero" in await materialize(io.stderr)


# GNU's ARGMATCH refusal names the refused word through gnulib's quote(),
# so a byte outside 0x20-0x7e comes back escaped. Rows measured against
# GNU coreutils 9.4 under `LC_ALL=C` with a raw `bytes` argv
# (`sort --check=<w>`). Mirrored in sort.test.ts.
@pytest.mark.parametrize("value,escaped", [
    ("xé", r"x\303\251"),
    ("x\r", r"x\r"),
    ("x\x01", r"x\001"),
    ("x\x7f", r"x\177"),
    ("x'", r"x\'"),
    ("x\\", r"x\\"),
])
def test_check_refusal_quotes_the_word(value, escaped):
    with pytest.raises(UsageError) as exc:
        parse_flags({"check": value})
    assert str(exc.value).startswith(
        f"sort: invalid argument '{escaped}' for '--check'\n")


def test_check_refusal_carries_gnus_candidate_block_and_exit_1():
    """Measured, coreutils 9.4: `sort --check=x f` is SIX lines, exit 1.

    `quiet` and `silent` are aliases of one value, so gnulib's
    `argmatch_valid` puts them on one `  - ` row. The exit is 1, not
    sort's usual usage code of 2, because `argmatch_die` always calls
    `usage (EXIT_FAILURE)`.
    """
    with pytest.raises(UsageError) as exc:
        parse_flags({"check": "x"})
    assert str(exc.value) == ("sort: invalid argument 'x' for '--check'\n"
                              "Valid arguments are:\n"
                              "  - 'quiet', 'silent'\n"
                              "  - 'diagnose-first'\n"
                              "Try 'sort --help' for more information.")
    assert exc.value.exit_code == 1


def test_an_empty_check_is_ambiguous():
    """`sort --check=` is `ambiguous argument ''`, exit 1 (measured)."""
    with pytest.raises(UsageError) as exc:
        parse_flags({"check": ""})
    assert str(
        exc.value).startswith("sort: ambiguous argument '' for '--check'\n")
    assert exc.value.exit_code == 1


# gnulib's argmatch resolves an unambiguous prefix of one candidate, so
# `sort --check=q`, `=s` and `=d` all exit 0 (measured, coreutils 9.4).
# `quiet` and `silent` are one value, so its canonical word decides
# whether the check is quiet.
def test_check_accepts_an_unambiguous_prefix():
    assert parse_flags({"check": "q"}).check_quiet
    assert parse_flags({"check": "s"}).check_quiet
    assert parse_flags({"check": "silent"}).check_quiet
    assert parse_flags({"check": "quiet"}).check_quiet
    assert not parse_flags({"check": "d"}).check_quiet
    assert not parse_flags({"check": "diagnose"}).check_quiet
    assert parse_flags({"check": "d"}).check


def test_check_still_refuses_a_word_no_candidate_starts_with():
    with pytest.raises(UsageError) as exc:
        parse_flags({"check": "qu1et"})
    assert str(
        exc.value).startswith("sort: invalid argument 'qu1et' for '--check'\n")


def _spec(virtual: str, raw: str | None = None) -> PathSpec:
    return PathSpec(virtual=virtual,
                    directory=virtual[:virtual.rfind("/") + 1],
                    vfs_path=virtual,
                    raw_path=raw)


def _reader(
    files: dict[str,
                bytes | OSError]) -> Callable[[PathSpec], Awaitable[bytes]]:

    async def read_bytes(path: PathSpec) -> bytes:
        value = files[path.virtual]
        if isinstance(value, OSError):
            raise value
        return value

    return read_bytes


async def _stderr(io: IOResult) -> bytes:
    return await materialize(io.stderr) if io.stderr is not None else b""


# Every row below was measured against GNU coreutils 9.7 on
# debian:stable-slim under LC_ALL=C.
@pytest.mark.asyncio
async def test_a_missing_input_is_cannot_read_and_exits_two():
    _, io = await sort([_spec("/data/missing.txt")],
                       read_bytes=_reader({
                           "/data/missing.txt":
                           FileNotFoundError("/data/missing.txt")
                       }),
                       flags={})
    assert await _stderr(io) == (b"sort: cannot read: /data/missing.txt: "
                                 b"No such file or directory\n")
    assert io.exit_code == 2


@pytest.mark.asyncio
async def test_the_input_is_named_as_typed_and_quoted_when_it_needs_it():
    _, io = await sort([_spec("/data/no such.txt", "no such.txt")],
                       read_bytes=_reader({
                           "/data/no such.txt":
                           FileNotFoundError("/data/no such.txt")
                       }),
                       flags={})
    assert await _stderr(io) == (b"sort: cannot read: 'no such.txt': "
                                 b"No such file or directory\n")


@pytest.mark.asyncio
async def test_a_directory_is_read_failed_and_waits_behind_a_missing_input():
    files: dict[str, bytes | OSError] = {
        "/data/dir": IsADirectoryError("/data/dir"),
        "/data/missing.txt": FileNotFoundError("/data/missing.txt"),
    }
    _, io = await sort([_spec("/data/dir")],
                       read_bytes=_reader(files),
                       flags={})
    assert await _stderr(io) == (b"sort: read failed: /data/dir: "
                                 b"Is a directory\n")
    assert io.exit_code == 2
    _, io = await sort(
        [_spec("/data/dir"), _spec("/data/missing.txt")],
        read_bytes=_reader(files),
        flags={})
    assert await _stderr(io) == (b"sort: cannot read: /data/missing.txt: "
                                 b"No such file or directory\n")


@pytest.mark.asyncio
async def test_the_first_input_to_fail_its_access_check_ends_the_run():
    files: dict[str, bytes | OSError] = {
        "/data/m1": FileNotFoundError("/data/m1"),
    }
    _, io = await sort(
        [_spec("/data/m1"), _spec("/data/m2")],
        read_bytes=_reader(files),
        flags={})
    assert await _stderr(io) == (b"sort: cannot read: /data/m1: "
                                 b"No such file or directory\n")


@pytest.mark.asyncio
@pytest.mark.parametrize("flags,verb", [
    ({}, b"stat failed"),
    ({
        "merge": True
    }, b"read failed"),
    ({
        "c": True
    }, b"read failed"),
])
async def test_a_closed_stdin_fails_where_gnu_first_touches_it(flags, verb):
    _, io = await sort([],
                       read_bytes=_unused_read_bytes,
                       stdin=unreadable_stdin(),
                       flags=flags)
    assert await _stderr(io
                         ) == b"sort: " + verb + b": -: Bad file descriptor\n"
    assert io.exit_code == 2


@pytest.mark.asyncio
async def test_check_opens_its_input_rather_than_testing_access():
    _, io = await sort([_spec("/data/missing.txt")],
                       read_bytes=_reader({
                           "/data/missing.txt":
                           FileNotFoundError("/data/missing.txt")
                       }),
                       flags={"C": True})
    assert await _stderr(io) == (b"sort: open failed: /data/missing.txt: "
                                 b"No such file or directory\n")
    assert io.exit_code == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("failure,strerror", [
    (FileNotFoundError("/data/nodir/out.txt"), b"No such file or directory"),
    (IsADirectoryError("/data/nodir/out.txt"), b"Is a directory"),
])
async def test_an_output_that_will_not_open_is_open_failed(failure, strerror):

    async def write_bytes(_path: PathSpec, _data: bytes) -> None:
        raise failure

    _, io = await sort([],
                       read_bytes=_unused_read_bytes,
                       write_bytes=write_bytes,
                       stdin=b"b\na\n",
                       flags={"output": [_spec("/data/nodir/out.txt")]})
    assert await _stderr(io) == (b"sort: open failed: /data/nodir/out.txt: " +
                                 strerror + b"\n")
    assert io.exit_code == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("flags,mode", [
    ({
        "c": True
    }, "c"),
    ({
        "C": True
    }, "C"),
    ({
        "check": True
    }, "c"),
    ({
        "check": "quiet"
    }, "C"),
    ({
        "check": "silent"
    }, "C"),
    ({
        "check": "diagnose-first"
    }, "c"),
])
async def test_check_refuses_an_output_by_its_own_letter(flags, mode):
    flags = {**flags, "output": [_spec("/data/out.txt")]}
    _, io = await sort([],
                       read_bytes=_unused_read_bytes,
                       stdin=b"b\na\n",
                       flags=flags)
    assert await _stderr(io) == (
        f"sort: options '-{mode}o' are incompatible\n".encode())
    assert io.exit_code == 2


@pytest.mark.asyncio
async def test_a_second_operand_outranks_the_output_and_names_the_mode():
    _, io = await sort([_spec("/data/a"), _spec("/data/b")],
                       read_bytes=_unused_read_bytes,
                       flags={
                           "C": True,
                           "output": [_spec("/data/out.txt")]
                       })
    assert await _stderr(io) == (
        b"sort: extra operand '/data/b' not allowed with -C\n")
    assert io.exit_code == 2


@pytest.mark.asyncio
async def test_quiet_check_is_silent_and_exits_one():
    _, io = await sort([],
                       read_bytes=_unused_read_bytes,
                       stdin=b"b\na\n",
                       flags={"C": True})
    assert await _stderr(io) == b""
    assert io.exit_code == 1


@pytest.mark.parametrize("flags", [
    {
        "c": True,
        "C": True
    },
    {
        "C": True,
        "c": True
    },
    {
        "c": True,
        "check": "quiet"
    },
    {
        "check": "silent",
        "c": True
    },
    {
        "C": True,
        "check": True
    },
])
def test_the_two_check_modes_refuse_to_mix(flags):
    with pytest.raises(UsageError) as exc:
        parse_flags(flags)
    assert str(exc.value) == "sort: options '-cC' are incompatible"
    assert exc.value.exit_code == 2


def test_one_mode_may_be_asked_for_twice():
    assert parse_flags({"C": True, "check": "quiet"}).check_quiet
    assert parse_flags({"c": True, "check": "diagnose-first"}).check


def test_two_outputs_are_refused_unless_they_name_one_file():
    with pytest.raises(UsageError) as exc:
        parse_flags({"output": [_spec("/data/p1"), _spec("/data/p2")]})
    assert str(exc.value) == "sort: multiple output files specified"
    assert exc.value.exit_code == 2
    parsed = parse_flags({"output": [_spec("/data/p1"), _spec("/data/p1")]})
    assert parsed.output is not None and parsed.output.virtual == "/data/p1"


def test_two_outputs_are_told_apart_by_the_word_typed():
    # GNU compares -o values with STREQ: `-o ./out -o out` is refused
    # although both name one file (coreutils 9.7).
    def typed(raw: str) -> PathSpec:
        return PathSpec(virtual="/data/out",
                        directory="/data/",
                        vfs_path="out",
                        raw_path=raw)

    with pytest.raises(UsageError) as exc:
        parse_flags({"output": [typed("./out"), typed("out")]})
    assert str(exc.value) == "sort: multiple output files specified"
    parsed = parse_flags({"output": [typed("out"), typed("out")]})
    assert parsed.output is not None and parsed.output.raw_path == "out"


def test_the_first_bad_option_on_the_line_is_the_one_refused():
    outputs = [_spec("/data/p1"), _spec("/data/p2")]
    with pytest.raises(UsageError):
        parse_flags({"output": outputs, "key": ["0"]})
    with pytest.raises(SortKeyError):
        parse_flags({"key": ["0"], "output": outputs})
    with pytest.raises(UsageError) as exc:
        parse_flags({"c": True, "C": True, "output": outputs})
    assert "'-cC'" in str(exc.value)


_MIXED = {"numeric_sort": True, "general_numeric_sort": True}


@pytest.mark.asyncio
@pytest.mark.parametrize("flags,refusal", [
    ({
        "key": ["0"]
    }, b"sort: field number is zero: invalid field specification '0'\n"),
    ({
        "output": [_spec("/data/p1"), _spec("/data/p2")]
    }, b"sort: multiple output files specified\n"),
    ({
        "c": True,
        "C": True
    }, b"sort: options '-cC' are incompatible\n"),
])
async def test_the_option_loop_outranks_incompatible_orderings(flags, refusal):
    _, io = await sort([],
                       read_bytes=_unused_read_bytes,
                       stdin=b"a\n",
                       flags={
                           **_MIXED,
                           **flags
                       })
    assert await _stderr(io) == refusal
    assert io.exit_code == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("paths,flags", [
    (["/data/a", "/data/b"], {
        "c": True
    }),
    (["/data/a"], {
        "c": True,
        "output": [_spec("/data/out")]
    }),
    (["/data/missing"], {}),
])
async def test_incompatible_orderings_outrank_the_operands(paths, flags):
    _, io = await sort([_spec(path) for path in paths],
                       read_bytes=_reader({
                           "/data/missing":
                           FileNotFoundError("/data/missing")
                       }),
                       flags={
                           **_MIXED,
                           **flags
                       })
    assert await _stderr(io) == b"sort: options '-gn' are incompatible\n"
    assert io.exit_code == 2


@pytest.mark.asyncio
async def test_each_input_ends_its_own_last_line():
    stdout, io = await sort(
        [_spec("/data/f1"), _spec("/data/f2")],
        read_bytes=_reader({
            "/data/f1": b"b",
            "/data/f2": b"a\n"
        }),
        flags={})
    assert await materialize(stdout) == b"a\nb\n"
    assert io.exit_code == 0


@pytest.mark.asyncio
async def test_merge_trusts_its_inputs_and_never_reorders_one():
    stdout, _ = await sort([_spec("/data/in.txt")],
                           read_bytes=_reader({"/data/in.txt": b"b\na\n"}),
                           flags={"merge": True})
    assert await materialize(stdout) == b"b\na\n"
    stdout, _ = await sort(
        [_spec("/data/s1"), _spec("/data/s2")],
        read_bytes=_reader({
            "/data/s1": b"c\na\n",
            "/data/s2": b"b\n"
        }),
        flags={"merge": True})
    assert await materialize(stdout) == b"b\nc\na\n"


@pytest.mark.parametrize("argv, message", [
    (["-o", "out", "-k", "2,2", "-k", "0", "-o", "out2"
      ], "field number is zero"),
    (["-k", "2,2", "-o", "out", "-o", "out2", "-k", "0"
      ], "multiple output files"),
    (["--check", "--check=quiet"], "options '-cC' are incompatible"),
])
def test_interleaved_occurrences_refuse_the_first_invalid_option(
        argv, message):
    flags = parse_to_kwargs(parse_command(SPECS["sort"], argv, "/data",
                                          "sort"))
    with pytest.raises((UsageError, SortKeyError), match=message):
        parse_flags(flags)
