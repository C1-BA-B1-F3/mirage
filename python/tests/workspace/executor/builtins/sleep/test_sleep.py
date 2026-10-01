import asyncio
import time

import pytest

from mirage.commands.spec import SPECS
from mirage.commands.spec.standard import help_page, version_line
from mirage.workspace.executor.builtins.sleep import handle_sleep


async def _stdout(source) -> bytes:
    if source is None:
        return b""
    return b"".join([chunk async for chunk in source])


# Measured on coreutils 9.4: the missing operand is the same
# `usage (EXIT_FAILURE)` refusal the invalid interval is, so it carries
# the same Try-help line.
@pytest.mark.asyncio
async def test_sleep_missing_operand_exits_1():
    _, io, node = await handle_sleep([])
    assert io.exit_code == 1
    assert io.stderr == (
        b"sleep: missing operand\nTry 'sleep --help' for more information.\n"
    )
    assert node.exit_code == 1


# sleep declares no options and reads the line through a real
# getopt_long loop, so a dash word it does not know is the option
# refusal and never the interval one, wherever it sits (measured on 9.4:
# `sleep --zzz 0` and `sleep 0 --zzz` both report the option).
@pytest.mark.asyncio
@pytest.mark.parametrize("args", [["--zzz"], ["--zzz", "0"], ["0", "--zzz"]])
async def test_sleep_unknown_long_option_exits_1(args):
    _, io, node = await handle_sleep(args)
    assert io.exit_code == 1
    assert io.stderr == (
        b"sleep: unrecognized option '--zzz'\n"
        b"Try 'sleep --help' for more information.\n"
    )
    assert node.exit_code == 1


# sleep's only options are gnulib's two standard ones, and they go
# through a real getopt_long loop: measured on 9.7, `--help`, `--h`,
# `--version` and `--v` all print to stdout and exit 0, wherever on the
# line they sit, and the first dash word decides (`sleep --help --zzz` is
# help, `sleep --zzz --help` is the refusal).
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "args",
    [
        ["--help"],
        ["--h"],
        ["--hel"],
        ["0", "--help"],
        ["--help", "--zzz"],
        ["--help", "0"],
    ],
)
async def test_sleep_help_prints_to_stdout_and_exits_0(args):
    out, io, node = await handle_sleep(args)
    assert io.exit_code == 0
    assert not io.stderr
    assert await _stdout(out) == help_page("sleep", SPECS["sleep"])
    assert node.exit_code == 0


# The page has to document the grammar this arm implements, which the
# declared spec alone cannot: sleep is a shell builtin, so nothing
# injects the two standard options into SPECS["sleep"], and rendering
# that spec produced a page naming neither of the options it was
# answering. Asserted on the CONTENT rather than against the renderer,
# because the version that asserted `render_help(spec)` was true of the
# page whatever the page said.
@pytest.mark.asyncio
async def test_sleep_help_documents_both_options_under_gnus_synopsis():
    out, _, _ = await handle_sleep(["--help"])
    page = (await _stdout(out)).decode()
    # coreutils 9.7 heads the page `Usage: sleep NUMBER[SUFFIX]...` and
    # lists both options; mirage renders its own layout under GNU's own
    # synopsis line rather than copying the page verbatim.
    assert "Usage: sleep NUMBER[SUFFIX]...\n" in page
    assert "[<text>...]" not in page
    for option in ("--help", "--version"):
        assert f"  {option}" in page


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "args", [["--version"], ["--v"], ["--ver"], ["0", "--version"]]
)
async def test_sleep_version_prints_to_stdout_and_exits_0(args):
    out, io, _ = await handle_sleep(args)
    assert io.exit_code == 0
    assert await _stdout(out) == version_line("sleep")


# getopt_long recognized the option and refused the VALUE, so the
# message names the canonical spelling and drops the value.
@pytest.mark.asyncio
@pytest.mark.parametrize("arg", ["--help=x", "--hel=x", "--version=x"])
async def test_sleep_standard_option_with_a_value_is_refused(arg):
    canonical = "--version" if arg.startswith("--vers") else "--help"
    _, io, _ = await handle_sleep([arg])
    assert io.exit_code == 1
    assert (
        io.stderr
        == (
            f"sleep: option '{canonical}' doesn't allow an argument\n"
            f"Try 'sleep --help' for more information.\n"
        ).encode()
    )


# An empty long name prefixes both standard options, and getopt_long
# quotes the WHOLE token in that refusal where the value one quotes the
# canonical spelling (measured on 9.7).
@pytest.mark.asyncio
async def test_sleep_empty_long_name_is_ambiguous():
    _, io, _ = await handle_sleep(["--=x"])
    assert io.exit_code == 1
    assert io.stderr == (
        b"sleep: option '--=x' is ambiguous; "
        b"possibilities: '--help' '--version'\n"
        b"Try 'sleep --help' for more information.\n"
    )


# Prefix matching is byte-exact: a longer dash run and a different case
# both prefix nothing (measured on 9.7).
@pytest.mark.asyncio
@pytest.mark.parametrize("arg", ["---help", "--HELP"])
async def test_sleep_near_miss_spellings_are_unrecognized(arg):
    _, io, _ = await handle_sleep([arg])
    assert io.exit_code == 1
    assert (
        io.stderr
        == (
            f"sleep: unrecognized option '{arg}'\n"
            f"Try 'sleep --help' for more information.\n"
        ).encode()
    )


# `--` ends the scan, so the word after it is an interval, not a help
# request (measured on 9.7).
@pytest.mark.asyncio
async def test_sleep_help_after_end_of_options_is_an_interval():
    _, io, _ = await handle_sleep(["--", "--help"])
    assert io.exit_code == 1
    assert io.stderr == (
        b"sleep: invalid time interval '--help'\n"
        b"Try 'sleep --help' for more information.\n"
    )


# A short one names the offending character, GNU's other wording.
@pytest.mark.asyncio
async def test_sleep_unknown_short_option_names_the_character():
    _, io, _ = await handle_sleep(["-Q"])
    assert io.stderr == (
        b"sleep: invalid option -- 'Q'\n"
        b"Try 'sleep --help' for more information.\n"
    )


# The page this arm prints heads with GNU's own
# `Usage: sleep NUMBER[SUFFIX]...`, and gnulib's `apply_suffix` is what
# that promises: one trailing character, multiplying by 1, 60, 3600 or
# 86400. Measured on coreutils 9.7 -- `sleep 0.3s` and `sleep 0.005m`
# each take 0.3s, `sleep 0.0001h` takes 0.36s -- and asserted on the
# elapsed time rather than on the parse, because reading the suffix and
# then dropping the multiplier would satisfy any check of the exit code
# alone.
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw,seconds",
    [
        ("0.3s", 0.3),
        ("0.005m", 0.3),
        ("0.0001h", 0.36),
        ("0.0000035d", 0.3024),
    ],
)
async def test_sleep_scales_by_the_advertised_suffix(raw, seconds):
    started = time.monotonic()
    _, io, node = await handle_sleep([raw])
    elapsed = time.monotonic() - started
    assert io.exit_code == 0
    assert node.exit_code == 0
    # The same 10ms of slack the sum test takes: a timer may land a
    # millisecond early, and the bound still separates this from the
    # suffix being ignored (0.005m read as 0.005s).
    assert elapsed >= seconds - 0.01


# A suffixed operand sums with a bare one like any other.
@pytest.mark.asyncio
async def test_sleep_sums_suffixed_and_bare_operands():
    started = time.monotonic()
    _, io, _ = await handle_sleep(["0.05", "0.05s"])
    assert io.exit_code == 0
    assert time.monotonic() - started >= 0.09


# gnulib allows exactly ONE character after the number and switches on
# it in lowercase, so everything here is `invalid time interval` on 9.7:
# an uppercase suffix, two of them, a suffix with anything after it, a
# letter that is not one, and a bare suffix with no number.
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw",
    [
        "0S",
        "0M",
        "0H",
        "0D",
        "0.5S",
        "0ss",
        "0sx",
        "0n",
        "0b",
        "s",
        "1_0s",
        "0 s",
    ],
)
async def test_sleep_refuses_a_suffix_gnulib_does_not_take(raw):
    _, io, _ = await handle_sleep(["--", raw])
    assert io.exit_code == 1
    assert io.stderr.startswith(
        f"sleep: invalid time interval '{raw}'\n".encode()
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw",
    ["abc", "-1", "inf", "Infinity", "nan", "NaN", "0x10", "1_0", "1e309", ""],
)
async def test_sleep_invalid_interval_exits_1(raw):
    _, io, node = await handle_sleep([raw])
    assert io.exit_code == 1
    assert (
        io.stderr
        == (
            f"sleep: invalid time interval '{raw}'\n"
            f"Try 'sleep --help' for more information.\n"
        ).encode()
    )
    assert node.exit_code == 1


# `NUMBER[SUFFIX]...`: sleep takes any number of intervals and sleeps
# their sum (measured on 9.7: `sleep 0.3 0.3` takes 0.6s, `sleep 0 1`
# takes 1s). Reading only the first operand made `sleep -- 0 1` return
# at once.
# The bound is 0.09 rather than 0.1 because the bug this guards against
# sleeps 0.05 (only the first operand), so 0.09 still separates the two by
# 40ms, while a timer is allowed to land a millisecond early. Mirrors the
# TypeScript twin, where CI measured 99ms for a 100ms wait.
@pytest.mark.asyncio
async def test_sleep_sums_every_operand():
    started = time.monotonic()
    _, io, node = await handle_sleep(["--", "0.05", "0.05"])
    elapsed = time.monotonic() - started
    assert io.exit_code == 0
    assert node.exit_code == 0
    assert elapsed >= 0.09


# Every operand is validated and EVERY bad one is named: coreutils calls
# `error()` per offending operand and only then `usage (EXIT_FAILURE)`,
# so the lines come in line order, a repeat repeats, and one Try-help
# line closes them (measured on 9.7: `sleep 1x 2y` is three lines,
# `sleep 1x 1x` names 1x twice, `sleep 1x 0 2y` skips the good one).
# Reading only the first operand made `sleep -- 0 bogus` exit 0.
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "args,named",
    [
        (["--", "0", "bogus"], ["bogus"]),
        (["0", "bogus"], ["bogus"]),
        (["bogus", "0"], ["bogus"]),
        (["--", "0.2", "x", "y"], ["x", "y"]),
        (["1x", "1x"], ["1x", "1x"]),
        (["1x", "0", "2y"], ["1x", "2y"]),
    ],
)
async def test_sleep_refuses_any_bad_operand_naming_every_one(args, named):
    _, io, node = await handle_sleep(args)
    assert io.exit_code == 1
    assert node.exit_code == 1
    lines = "".join(f"sleep: invalid time interval '{w}'\n" for w in named)
    assert (
        io.stderr
        == (f"{lines}Try 'sleep --help' for more information.\n").encode()
    )


# The SUM is what gets slept, so an operand that carries it past the
# representable range is refused like one that is not finite on its own.
# Each 1e308 passes the per-operand check, and the total overflowed to
# inf, which `asyncio.sleep` waits on forever -- the hang SLEEP_INTERVAL's
# `inf` divergence exists to prevent. GNU sleeps forever here too
# (measured on 9.7, as it does on `sleep inf`); refusing is the same
# deliberate divergence. The operand that overflowed is the one named,
# so a third one is a second diagnostic.
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "args,named",
    [
        (["1e308", "1e308"], ["1e308"]),
        (["1e308", "1e308", "1e308"], ["1e308", "1e308"]),
    ],
)
async def test_sleep_refuses_a_sum_that_overflows(args, named):
    _, io, node = await asyncio.wait_for(handle_sleep(args), timeout=5)
    assert io.exit_code == 1
    assert node.exit_code == 1
    lines = "".join(f"sleep: invalid time interval '{w}'\n" for w in named)
    assert (
        io.stderr
        == (f"{lines}Try 'sleep --help' for more information.\n").encode()
    )


# A total that stays representable is still slept, however large: only
# the overflow is refused, not a big number.
@pytest.mark.asyncio
async def test_sleep_keeps_a_large_but_representable_total():
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(handle_sleep(["1e308"]), timeout=0.2)


# The check runs over every operand before any of them is slept, so a
# bad one does not cost the wait its predecessors would have taken
# (measured on 9.7: `sleep 0.2 x 0.2` exits 1 immediately).
@pytest.mark.asyncio
async def test_sleep_checks_every_operand_before_sleeping_any():
    started = time.monotonic()
    _, io, _ = await handle_sleep(["0.3", "bogus"])
    elapsed = time.monotonic() - started
    assert io.exit_code == 1
    assert elapsed < 0.2


# The operand is named through gnulib's `quote()`, like every other
# coreutils operand diagnostic: measured on 9.4, `sleep -- <e-acute>` is
# `sleep: invalid time interval '\303\251'`.
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw,escaped",
    [("xé", r"x\303\251"), ("x\r", r"x\r"), ("--zzz=é", r"--zzz=\303\251")],
)
async def test_sleep_invalid_interval_quotes_the_word(raw, escaped):
    _, io, _ = await handle_sleep(["--", raw])
    assert (
        io.stderr
        == (
            f"sleep: invalid time interval '{escaped}'\n"
            f"Try 'sleep --help' for more information.\n"
        ).encode()
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", ["0", "0.", ".01", "+0.01", "1e-3"])
async def test_sleep_valid_interval_exits_0(raw):
    _, io, node = await handle_sleep([raw])
    assert io.exit_code == 0
    assert not io.stderr
    assert node.exit_code == 0


@pytest.mark.asyncio
async def test_sleep_zero_returns_promptly():
    start = time.monotonic()
    _, io, _ = await handle_sleep(["0"])
    assert io.exit_code == 0
    assert time.monotonic() - start < 0.05
