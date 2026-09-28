import asyncio

import pytest

from mirage.io import IOResult
from mirage.io.stream import materialize
from mirage.workspace.executor.builtins.xargs import handle_xargs
from mirage.workspace.session.session import SessionState


class FakeShell:

    def __init__(self, exit_codes: list[int] | None = None):
        self.lines: list[str] = []
        self.exit_codes = exit_codes or []

    async def __call__(self, line: str, session_id: str) -> IOResult:
        self.lines.append(line)
        code = (self.exit_codes[len(self.lines) - 1]
                if len(self.lines) <= len(self.exit_codes) else 0)
        return IOResult(stdout=f"ran:{line}\n".encode(), exit_code=code)


class SlowShell:

    def __init__(self,
                 delays: dict[str, float] | None = None,
                 exit_codes: dict[str, int] | None = None):
        self.lines: list[str] = []
        self.active = 0
        self.peak = 0
        self.delays = delays or {}
        self.exit_codes = exit_codes or {}

    async def __call__(self, line: str, session_id: str) -> IOResult:
        self.lines.append(line)
        self.active += 1
        self.peak = max(self.peak, self.active)
        await asyncio.sleep(self.delays.get(line, 0.01))
        self.active -= 1
        return IOResult(stdout=f"ran:{line}\n".encode(),
                        exit_code=self.exit_codes.get(line, 0))


TRY = b"Try 'xargs --help' for more information.\n"


def make_session() -> SessionState:
    return SessionState(session_id="s1")


def warned(option: str, offending: str) -> bytes:
    return (f"xargs: warning: options {offending} and {option} are mutually "
            f"exclusive, ignoring previous {offending} value\n").encode()


@pytest.mark.asyncio
async def test_batches_one_arg_per_run_with_n1():
    shell = FakeShell()
    _, io, _ = await handle_xargs(shell, ["-n1", "echo"], make_session(),
                                  b"a b c")
    assert shell.lines == ["echo a", "echo b", "echo c"]
    assert io.exit_code == 0


@pytest.mark.asyncio
async def test_single_run_without_n():
    shell = FakeShell()
    _, io, _ = await handle_xargs(shell, ["echo"], make_session(), b"a b c")
    assert shell.lines == ["echo a b c"]
    assert io.exit_code == 0


@pytest.mark.asyncio
async def test_failing_invocation_exits_123_but_continues():
    shell = FakeShell(exit_codes=[1, 0])
    _, io, _ = await handle_xargs(shell, ["-n1", "wc"], make_session(), b"a b")
    assert shell.lines == ["wc a", "wc b"]
    assert io.exit_code == 123


@pytest.mark.asyncio
async def test_command_not_found_stops_with_127():
    shell = FakeShell(exit_codes=[127, 0])
    _, io, _ = await handle_xargs(shell, ["-n1", "nope"], make_session(),
                                  b"a b")
    assert shell.lines == ["nope a"]
    assert io.exit_code == 127


@pytest.mark.asyncio
async def test_no_run_if_empty():
    shell = FakeShell()
    _, io, _ = await handle_xargs(shell, ["-r", "echo", "hi"], make_session(),
                                  b"")
    assert shell.lines == []
    assert io.exit_code == 0


@pytest.mark.asyncio
async def test_empty_input_without_r_runs_once():
    shell = FakeShell()
    _, io, _ = await handle_xargs(shell, ["echo", "hi"], make_session(), b"")
    assert shell.lines == ["echo hi"]
    assert io.exit_code == 0


@pytest.mark.asyncio
async def test_null_delimited_input():
    shell = FakeShell()
    await handle_xargs(shell, ["-0", "echo"], make_session(), b"a b\0c\0")
    assert shell.lines == ["echo 'a b' c"]


@pytest.mark.asyncio
async def test_custom_delimiter():
    shell = FakeShell()
    await handle_xargs(shell, ["-d,", "echo"], make_session(), b"a,b,c")
    assert shell.lines == ["echo a b c"]


@pytest.mark.asyncio
async def test_invalid_option_exits_1():
    shell = FakeShell()
    _, io, _ = await handle_xargs(shell, ["-q", "echo"], make_session(), b"x")
    assert io.exit_code == 1
    assert await materialize(io.stderr
                             ) == (b"xargs: invalid option -- 'q'\n" + TRY)
    assert shell.lines == []


@pytest.mark.asyncio
@pytest.mark.parametrize("args, message", [
    (["--bogus", "echo"], b"xargs: unrecognized option '--bogus'\n"),
    (["-n"], b"xargs: option requires an argument -- 'n'\n"),
    (["--max-args"], b"xargs: option '--max-args' requires an argument\n"),
    (["-I"], b"xargs: option requires an argument -- 'I'\n"),
])
async def test_option_refusals_carry_the_help_hint(args, message):
    shell = FakeShell()
    _, io, _ = await handle_xargs(shell, args, make_session(), b"x")
    assert io.exit_code == 1
    assert await materialize(io.stderr) == message + TRY
    assert shell.lines == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "args", [["--help"], ["--help", "-q"], ["-r", "--help", "echo"]])
async def test_help_prints_the_page_where_it_stands(args):
    shell = FakeShell()
    out, io, _ = await handle_xargs(shell, args, make_session(), b"x")
    page = (await materialize(out)).decode()
    assert page.startswith(
        "xargs: Build and run command lines from standard input.\n\n"
        "Usage: xargs [OPTION]... COMMAND [INITIAL-ARGS]...\n")
    assert "  -P, --max-procs <text>" in page
    assert io.exit_code == 0
    assert shell.lines == []


@pytest.mark.asyncio
async def test_version_and_an_earlier_refusal():
    shell = FakeShell()
    out, io, _ = await handle_xargs(shell, ["--version"], make_session(), b"x")
    assert (await materialize(out)).startswith(b"xargs (Mirage) ")
    assert io.exit_code == 0
    _, io, _ = await handle_xargs(shell, ["-n0", "--help"], make_session(),
                                  b"x")
    assert io.exit_code == 1
    assert await materialize(
        io.stderr) == (b"xargs: value 0 for -n option should be >= 1\n" + TRY)
    assert shell.lines == []


@pytest.mark.asyncio
async def test_n_zero_rejected():
    shell = FakeShell()
    _, io, _ = await handle_xargs(shell, ["-n0", "echo"], make_session(), b"x")
    assert io.exit_code == 1
    assert (await materialize(
        io.stderr)) == (b"xargs: value 0 for -n option should be >= 1\n" + TRY)


@pytest.mark.asyncio
async def test_input_words_stay_single_tokens():
    shell = FakeShell()
    await handle_xargs(shell, ["echo"], make_session(), b"don\\'t $(reboot)")
    assert shell.lines == ["echo 'don'\"'\"'t' '$(reboot)'"]


@pytest.mark.asyncio
async def test_quotes_and_backslashes_are_removed():
    shell = FakeShell()
    await handle_xargs(shell, ["-n1", "echo"], make_session(),
                       b"\"a b\" 'c  d' e\\ f \"\"\n")
    assert shell.lines == [
        "echo 'a b'", "echo 'c  d'", "echo 'e f'", "echo ''"
    ]


@pytest.mark.asyncio
async def test_unmatched_quote_runs_the_words_read_then_exits_1():
    shell = FakeShell()
    _, io, _ = await handle_xargs(shell, ["echo"], make_session(),
                                  b"a b\nc 'd\n")
    assert shell.lines == ["echo a b c"]
    assert io.exit_code == 1
    assert await materialize(
        io.stderr
    ) == (b"xargs: unmatched single quote; by default quotes are special to "
          b"xargs unless you use the -0 option\n")


@pytest.mark.asyncio
async def test_null_input_keeps_empty_items():
    shell = FakeShell()
    await handle_xargs(shell, ["-0", "echo"], make_session(), b"a\0\0b\0")
    assert shell.lines == ["echo a '' b"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "args", [["-I{}", "echo", "x{}y"], ["-I", "{}", "echo", "x{}y"]])
async def test_replace_runs_once_per_line(args):
    shell = FakeShell()
    _, io, _ = await handle_xargs(shell, args, make_session(), b"a\nb\n")
    assert shell.lines == ["echo xay", "echo xby"]
    assert io.exit_code == 0


@pytest.mark.asyncio
async def test_replace_takes_the_whole_line():
    shell = FakeShell()
    await handle_xargs(shell, ["-I{}", "echo", "[{}]"], make_session(),
                       b"one two\n  three  \n\n   \n\"a b\" c\n")
    assert shell.lines == [
        "echo '[one two]'", "echo '[three  ]'", "echo '[a b c]'"
    ]


@pytest.mark.asyncio
async def test_replace_substitutes_every_occurrence_but_not_the_name():
    shell = FakeShell()
    await handle_xargs(shell, ["-I%", "%", "%", "%-%", "x%%y"], make_session(),
                       b"a\n")
    assert shell.lines == ["% a a-a xaay"]


@pytest.mark.asyncio
async def test_replace_inserts_the_line_verbatim():
    shell = FakeShell()
    await handle_xargs(shell, ["-I{}", "echo", "<{}>"], make_session(),
                       b"$&\\'x\n")
    assert shell.lines == ["echo '<$&'\"'\"'x>'"]


@pytest.mark.asyncio
async def test_replace_on_empty_input_runs_nothing():
    shell = FakeShell()
    _, io, _ = await handle_xargs(shell, ["-I{}", "echo", "{}"],
                                  make_session(), b"")
    assert shell.lines == []
    assert io.exit_code == 0


@pytest.mark.asyncio
async def test_replace_with_null_and_delimiter_items():
    shell = FakeShell()
    await handle_xargs(shell, ["-0", "-I{}", "echo", "[{}]"], make_session(),
                       b"a b\0\0c\0")
    await handle_xargs(shell, ["-d,", "-I{}", "echo", "[{}]"], make_session(),
                       b"a,b")
    assert shell.lines == [
        "echo '[a b]'", "echo '[]'", "echo '[c]'", "echo '[a]'", "echo '[b]'"
    ]


@pytest.mark.asyncio
async def test_replace_failure_exits_123_and_missing_command_stops():
    shell = FakeShell(exit_codes=[1, 0])
    _, io, _ = await handle_xargs(shell, ["-I{}", "test", "{}"],
                                  make_session(), b"a\nb\n")
    assert shell.lines == ["test a", "test b"]
    assert io.exit_code == 123
    shell = FakeShell(exit_codes=[127, 0])
    _, io, _ = await handle_xargs(shell, ["-I{}", "nope", "{}"],
                                  make_session(), b"a\nb\n")
    assert shell.lines == ["nope a"]
    assert io.exit_code == 127


@pytest.mark.asyncio
async def test_replace_unmatched_quote_after_earlier_lines():
    shell = FakeShell()
    _, io, _ = await handle_xargs(shell, ["-I{}", "echo", "{}"],
                                  make_session(), b"a\nb 'c\n")
    assert shell.lines == ["echo a"]
    assert io.exit_code == 1


@pytest.mark.asyncio
async def test_empty_replace_string_is_command_too_long():
    shell = FakeShell()
    _, io, _ = await handle_xargs(shell, ["-I", "", "echo", "x"],
                                  make_session(), b"a\n")
    assert shell.lines == []
    assert io.exit_code == 1
    assert await materialize(io.stderr) == b"xargs: command too long\n"


@pytest.mark.asyncio
@pytest.mark.parametrize("args, data, lines", [
    (["-L", "2", "echo"], b"a\nb\nc\n", ["echo a b", "echo c"]),
    (["-L2", "echo"], b"a b\nc d\ne\n", ["echo a b c d", "echo e"]),
    (["-L1", "echo"], b"a b \nc d\ne\n", ["echo a b c d", "echo e"]),
    (["-L1", "echo"], b"a\\ \nb\n", ["echo 'a ' b"]),
    (["-L1", "echo"], b"a\n\n\nb\n", ["echo a", "echo b"]),
    (["-L1", "echo", "x"], b"\n\n", ["echo x"]),
    (["-L1", "-r", "echo", "x"], b"\n\n", []),
    (["-0", "-L1", "echo"], b"a b\0c\0", ["echo 'a b'", "echo c"]),
])
async def test_max_lines_batches_input_lines(args, data, lines):
    shell = FakeShell()
    _, io, _ = await handle_xargs(shell, args, make_session(), data)
    assert shell.lines == lines
    assert io.exit_code == 0


@pytest.mark.asyncio
async def test_max_lines_unmatched_quote_drops_the_partial_line():
    shell = FakeShell()
    _, io, _ = await handle_xargs(shell, ["-L1", "echo"], make_session(),
                                  b"a b\nc 'd\n")
    assert shell.lines == ["echo a b"]
    assert io.exit_code == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("args, message", [
    (["-L", "0"], b"xargs: value 0 for -L option should be >= 1\n"),
    (["-L", "-1"], b"xargs: value -1 for -L option should be >= 1\n"),
    (["-L", "x"], b'xargs: invalid number "x" for -L option\n'),
    (["-L", "2 "], b'xargs: invalid number "2 " for -L option\n'),
    (["-l0"], b"xargs: value 0 for -l option should be >= 1\n"),
    (["--max-lines=x"], b'xargs: invalid number "x" for -l option\n'),
    (["-l1r"], b'xargs: invalid number "1r" for -l option\n'),
    (["-P", "x"], b'xargs: invalid number "x" for -P option\n'),
    (["-P", "-1"], b"xargs: value -1 for -P option should be >= 0\n"),
    (["-P", "99999999999"
      ], b"xargs: value 99999999999 for -P option should be <= 2147483647\n"),
])
async def test_counts_are_refused_with_the_help_hint(args, message):
    shell = FakeShell()
    _, io, _ = await handle_xargs(shell, [*args, "echo"], make_session(),
                                  b"a\n")
    assert io.exit_code == 1
    assert await materialize(io.stderr) == message + TRY
    assert shell.lines == []


@pytest.mark.asyncio
@pytest.mark.parametrize("args, lines", [
    (["-i", "echo", "x{}y"], ["echo xay", "echo xby"]),
    (["-iZ", "echo", "xZy"], ["echo xay", "echo xby"]),
    (["--replace", "echo", "x{}y"], ["echo xay", "echo xby"]),
    (["--replace=Z", "echo", "xZy"], ["echo xay", "echo xby"]),
    (["-i", "Z", "x{}"], ["Z xa", "Z xb"]),
    (["-ri", "echo", "{}"], ["echo a", "echo b"]),
    (["-il", "echo", "{}"], ["echo '{}'", "echo '{}'"]),
    (["-l", "echo"], ["echo a", "echo b"]),
    (["-l2", "echo"], ["echo a b"]),
    (["--max-lines", "echo"], ["echo a", "echo b"]),
    (["--max-lines=2", "echo"], ["echo a b"]),
    (["-l", "2"], ["2 a", "2 b"]),
])
async def test_optional_value_replace_and_max_lines(args, lines):
    shell = FakeShell()
    _, io, _ = await handle_xargs(shell, args, make_session(), b"a\nb\n")
    assert shell.lines == lines
    assert io.exit_code == 0


@pytest.mark.asyncio
async def test_max_procs_runs_side_by_side_in_input_order():
    shell = SlowShell(delays={"echo a": 0.05})
    out, io, _ = await handle_xargs(shell, ["-P2", "-n1", "echo"],
                                    make_session(), b"a b c d")
    assert shell.lines == ["echo a", "echo b", "echo c", "echo d"]
    assert shell.peak == 2
    assert await materialize(out) == (
        b"ran:echo a\nran:echo b\nran:echo c\nran:echo d\n")
    assert io.exit_code == 0
    shell = SlowShell()
    await handle_xargs(shell, ["-P0", "-n1", "echo"], make_session(),
                       b"a b c d")
    assert shell.peak == 4
    shell = SlowShell()
    await handle_xargs(shell, ["-n1", "echo"], make_session(), b"a b c d")
    assert shell.peak == 1


@pytest.mark.asyncio
async def test_max_procs_starts_nothing_after_a_command_cannot_run():
    shell = SlowShell(delays={"nope b": 0.05}, exit_codes={"nope a": 127})
    _, io, _ = await handle_xargs(shell, ["-P2", "-n1", "nope"],
                                  make_session(), b"a b c d")
    assert shell.lines == ["nope a", "nope b"]
    assert io.exit_code == 127
    shell = SlowShell(exit_codes={"nope c": 1})
    _, io, _ = await handle_xargs(shell, ["-P3", "-n1", "nope"],
                                  make_session(), b"a b c d")
    assert io.exit_code == 123


@pytest.mark.asyncio
@pytest.mark.parametrize("args, lines, warnings", [
    (["-I{}", "-n1", "echo", "[{}]"], ["echo '[a b]'", "echo '[c]'"], []),
    (["-n1", "-I{}", "echo", "[{}]"], ["echo '[a b]'", "echo '[c]'"
                                       ], [("--replace/-I/-i", "--max-args")]),
    (["-L2", "-I{}", "echo", "[{}]"
      ], ["echo '[a b]'", "echo '[c]'"], [("--replace/-I/-i", "--max-lines")]),
    (["-I{}", "-L2", "echo", "[{}]"], ["echo '[{}]' a b c"
                                       ], [("-L", "--replace")]),
    (["-I{}", "-n2", "echo", "[{}]"], ["echo '[{}]' a b", "echo '[{}]' c"
                                       ], [("--max-args/-n", "--replace")]),
    (["-L1", "-n2", "echo"], ["echo a b", "echo c"
                              ], [("--max-args/-n", "--max-lines")]),
    (["-n2", "-L1", "echo"], ["echo a b", "echo c"], [("-L", "--max-args")]),
    (["-n2", "-l", "echo"], ["echo a b", "echo c"
                             ], [("--max-lines/-l", "--max-args")]),
    (["-i", "-l", "echo", "{}"], ["echo '{}' a b", "echo '{}' c"
                                  ], [("--max-lines/-l", "--replace")]),
    (["-L1", "-n2", "-L1", "echo"], ["echo a b", "echo c"
                                     ], [("--max-args/-n", "--max-lines"),
                                         ("-L", "--max-args")]),
    (["-n1", "-I{}", "-n1", "echo", "[{}]"
      ], ["echo '[a b]'", "echo '[c]'"], [("--replace/-I/-i", "--max-args")]),
])
async def test_replace_max_lines_and_max_args_cancel_in_order(
        args, lines, warnings):
    shell = FakeShell()
    _, io, _ = await handle_xargs(shell, args, make_session(), b"a b\nc\n")
    assert shell.lines == lines
    stderr = await materialize(io.stderr) or b""
    assert stderr == b"".join(warned(o, off) for o, off in warnings)
