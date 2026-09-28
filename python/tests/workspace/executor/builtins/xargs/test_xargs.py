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


def make_session() -> SessionState:
    return SessionState(session_id="s1")


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
    assert await materialize(io.stderr) == b"xargs: invalid option -- 'q'\n"
    assert shell.lines == []


@pytest.mark.asyncio
async def test_unsupported_option_exits_1():
    shell = FakeShell()
    _, io, _ = await handle_xargs(shell, ["-P2", "echo"], make_session(), b"x")
    assert io.exit_code == 1
    assert await materialize(io.stderr
                             ) == b"xargs: unsupported option -- 'P'\n"
    assert shell.lines == []


@pytest.mark.asyncio
async def test_n_zero_rejected():
    shell = FakeShell()
    _, io, _ = await handle_xargs(shell, ["-n0", "echo"], make_session(), b"x")
    assert io.exit_code == 1
    assert (await
            materialize(io.stderr
                        )) == b"xargs: value 0 for -n option should be >= 1\n"


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
@pytest.mark.parametrize("value, message", [
    ("0", b"xargs: value 0 for -L option should be >= 1\n"),
    ("-1", b"xargs: value -1 for -L option should be >= 1\n"),
    ("x", b'xargs: invalid number "x" for -L option\n'),
    ("2 ", b'xargs: invalid number "2 " for -L option\n'),
])
async def test_max_lines_refuses_a_bad_count(value, message):
    shell = FakeShell()
    _, io, _ = await handle_xargs(shell, ["-L", value, "echo"], make_session(),
                                  b"a\n")
    assert io.exit_code == 1
    assert await materialize(io.stderr) == message
    assert shell.lines == []


@pytest.mark.asyncio
@pytest.mark.parametrize("args, lines, warning", [
    (["-I{}", "-n1", "echo", "[{}]"], ["echo '[a b]'", "echo '[c]'"], b""),
    (["-n1", "-I{}", "echo", "[{}]"], ["echo '[a b]'", "echo '[c]'"],
     b"options --max-args and --replace/-I/-i"),
    (["-L2", "-I{}", "echo", "[{}]"], ["echo '[a b]'", "echo '[c]'"],
     b"options --max-lines and --replace/-I/-i"),
    (["-I{}", "-L2", "echo", "[{}]"], ["echo '[{}]' a b c"
                                       ], b"options --replace and -L"),
    (["-I{}", "-n2", "echo", "[{}]"], ["echo '[{}]' a b", "echo '[{}]' c"],
     b"options --replace and --max-args/-n"),
    (["-L1", "-n2", "echo"], ["echo a b", "echo c"
                              ], b"options --max-lines and --max-args/-n"),
    (["-n2", "-L1", "echo"], ["echo a b", "echo c"
                              ], b"options --max-args and -L"),
    (["-L1", "-n2", "-L1", "echo"], ["echo a b", "echo c"
                                     ], b"options --max-args and -L"),
])
async def test_replace_max_lines_and_max_args_cancel_in_order(
        args, lines, warning):
    shell = FakeShell()
    _, io, _ = await handle_xargs(shell, args, make_session(), b"a b\nc\n")
    assert shell.lines == lines
    stderr = await materialize(io.stderr) or b""
    if warning:
        assert stderr == (b"xargs: warning: " + warning +
                          b" are mutually exclusive, ignoring previous " +
                          warning.split()[1] + b" value\n")
    else:
        assert stderr == b""
