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

from mirage.commands.builtin.generic.cmp import (cmp_cmd, parse_count,
                                                 parse_flags, parse_skip,
                                                 visible)
from mirage.commands.errors import UsageError
from mirage.io.stream import materialize
from mirage.types import PathSpec

P1 = PathSpec.from_str_path("/F/one", "")
P2 = PathSpec.from_str_path("/F/two", "")
DASH = PathSpec(virtual="/F/-", directory="/F/", vfs_path="-", raw_path="-")
DEV_STDIN = PathSpec.from_str_path("/dev/stdin", "")


def _reader(first: bytes, second: bytes):

    async def read_bytes(path: PathSpec) -> bytes:
        return first if path.virtual == P1.virtual else second

    return read_bytes


async def _run(first: bytes, second: bytes, **kwargs):
    src, io = await cmp_cmd([P1, P2],
                            read_bytes=_reader(first, second),
                            **kwargs)
    out = b"" if src is None else await materialize(src)
    return out.decode(), (io.stderr or b"").decode(), io.exit_code


def test_parse_count_takes_digits_and_gnu_size_suffixes():
    assert parse_count("4", "--bytes") == 4
    assert parse_count("1K", "--bytes") == 1024
    assert parse_count("1k", "--bytes") == 1024
    assert parse_count("1kB", "--bytes") == 1000
    assert parse_count("1kiB", "--bytes") == 1024
    assert parse_count("1M", "--bytes") == 1024 * 1024


@pytest.mark.parametrize("raw", ["1b", "1B", "1c", "1w", "1m", "1g", "1t"])
def test_parse_count_rejects_the_letters_od_takes_and_cmp_does_not(raw):
    # diffutils 3.10 lists only kB/K/MB/M/... : no block or char
    # suffixes, and lowercase only as far as k. `cmp -n 1b` is exit 2,
    # where od would read it as 512 bytes.
    with pytest.raises(UsageError):
        parse_count(raw, "--bytes")


def test_parse_count_names_the_long_option_it_was_given():
    # GNU says `invalid --bytes value` for -n and `invalid
    # --ignore-initial value` for -i, exit 2. diffutils routes the
    # Try-help line through error(), so it carries the `cmp: ` prefix
    # that coreutils' bare hint does not.
    with pytest.raises(UsageError) as excinfo:
        parse_count("abc", "--bytes")
    assert str(excinfo.value) == ("cmp: invalid --bytes value 'abc'\n"
                                  "cmp: Try 'cmp --help' for more "
                                  "information.")
    assert excinfo.value.exit_code == 2


def test_parse_count_rejects_an_unknown_suffix():
    # Q and R postdate the gnulib diffutils 3.10 was built against, so
    # they are invalid values rather than overflowing ones: `0Q` fails
    # where `0Z` is a valid zero.
    with pytest.raises(UsageError):
        parse_count("1Q", "--bytes")
    with pytest.raises(UsageError):
        parse_count("0Q", "--bytes")
    assert parse_count("0Z", "--bytes") == 0


def test_parse_count_reads_the_digits_at_base_zero():
    # xstrtoumax's base 0, which python's own int(s, 0) will not do:
    # a bare leading zero is octal and 0x is hex.
    assert parse_count("010", "--bytes") == 8
    assert parse_count("0x400", "--bytes") == 1024
    assert parse_count("+1010", "--bytes") == 1010
    assert parse_count(" 1", "--bytes") == 1
    with pytest.raises(UsageError):
        parse_count("1 ", "--bytes")
    with pytest.raises(UsageError):
        parse_count("-1", "--bytes")


def test_parse_count_rejects_a_product_past_intmax():
    # The ceiling is INTMAX, not UINTMAX, and overflow reports as the
    # same invalid-value error as a bad suffix -- not od's "too large".
    assert parse_count("9223372036854775807", "--bytes") == 2**63 - 1
    assert parse_count("7E", "--bytes") == 7 * 1024**6
    for raw in ("9223372036854775808", "8E", "1Z", "1Y"):
        with pytest.raises(UsageError):
            parse_count(raw, "--bytes")


def test_parse_skip_takes_one_count_for_both_files():
    assert parse_skip("3") == (3, 3)


@pytest.mark.parametrize("raw,named", [
    ("1b:1", "1b:1"),
    ("1:1b", "1b"),
    ("1:abc", "abc"),
    ("abc:1", "abc:1"),
    ("1:2:3", "2:3"),
    ("1:", ""),
    (":1", ":1"),
    (":", ":"),
])
def test_parse_skip_names_the_operand_from_where_it_stopped(raw, named):
    # GNU prints the operand from the position xstrtoumax was reading,
    # so a bad SKIP1 names the whole pair and a bad SKIP2 names only
    # itself. A colon is the one character the first count may stop on.
    with pytest.raises(UsageError) as excinfo:
        parse_skip(raw)
    assert str(excinfo.value).splitlines()[0] == (
        f"cmp: invalid --ignore-initial value '{named}'")


def test_parse_skip_takes_a_colon_pair_for_one_each():
    assert parse_skip("0:3") == (0, 3)
    assert parse_skip("1K:2") == (1024, 2)


@pytest.mark.parametrize("byte,rendered", [
    (ord("b"), "b"),
    (9, "^I"),
    (1, "^A"),
    (127, "^?"),
    (0xC3, "M-C"),
    (0xA9, "M-)"),
    (0x80, "M-^@"),
])
def test_visible_renders_one_byte_the_cat_v_way(byte, rendered):
    assert visible(byte) == rendered


@pytest.mark.asyncio
async def test_print_bytes_switches_the_word_to_byte():
    # GNU counts in `byte` under -b and in `char` otherwise.
    plain, _, _ = await _run(b"abc", b"aXc")
    tagged, _, _ = await _run(b"abc", b"aXc", print_bytes=True)
    assert plain == "/F/one /F/two differ: char 2, line 1\n"
    assert tagged == ("/F/one /F/two differ: byte 2, line 1"
                      " is 142 b 130 X\n")


@pytest.mark.asyncio
async def test_verbose_pads_the_octal_to_three_columns():
    out, _, _ = await _run(b"a\x01c", b"a\x7fc", verbose=True)
    assert out == "2   1 177\n"


@pytest.mark.asyncio
async def test_verbose_with_print_bytes_adds_a_four_wide_char_column():
    out, _, _ = await _run(b"abc", b"aXc", verbose=True, print_bytes=True)
    assert out == "2 142 b    130 X\n"


@pytest.mark.asyncio
async def test_skip_is_applied_per_file():
    # `-i 0:3` keeps all of the first file and drops three bytes of the
    # second, so the very first compared byte differs.
    out, _, code = await _run(b"abcdefgh", b"abcXefgh", skip=(0, 3))
    assert out == "/F/one /F/two differ: char 1, line 1\n"
    assert code == 1


@pytest.mark.asyncio
async def test_eof_is_a_stderr_diagnostic_naming_the_byte_and_line():
    out, err, code = await _run(b"ab\nc", b"ab\ncdef")
    assert out == ""
    assert err == "cmp: EOF on /F/one after byte 4, in line 2\n"
    assert code == 1


@pytest.mark.asyncio
async def test_verbose_eof_reports_the_byte_without_the_line():
    out, err, code = await _run(b"aXc", b"aYcdef", verbose=True)
    assert out == "2 130 131\n"
    assert err == "cmp: EOF on /F/one after byte 3\n"
    assert code == 1


@pytest.mark.asyncio
async def test_a_limit_inside_the_common_prefix_reports_no_difference():
    assert await _run(b"abcdef", b"abcXef", limit=2) == ("", "", 0)


@pytest.mark.parametrize("value", ["1é", "1\x01", "1\r", "1'", "1\\"])
def test_parse_count_leaves_the_value_unescaped(value):
    """`cmp -n` quotes the value but does NOT escape it.

    diffutils is not coreutils: it interpolates the bytes with a plain
    `%s` inside the quotes rather than passing them through gnulib's
    `quote()`, so a control byte, a backslash and a single quote all
    reach stderr as themselves. Measured against GNU diffutils' cmp
    under `LC_ALL=C` with a raw `bytes` argv: `cmp -n 1é` reports
    `invalid --bytes value '1é'` and `cmp -n "1'"` reports
    `'1''`, where the coreutils clauses next door would say
    `'1\\303\\251'` and `'1\\''`. This asymmetry is deliberate; do not
    "fix" it by routing this clause through quote().
    """
    with pytest.raises(UsageError) as exc:
        parse_count(value, "--bytes")
    assert str(exc.value) == (f"cmp: invalid --bytes value '{value}'\n"
                              "cmp: Try 'cmp --help' for more information.")


async def _run_with_stdin(paths: list[PathSpec], stdin: bytes, second: bytes,
                          **kwargs):

    async def read_bytes(path: PathSpec) -> bytes:
        assert path.virtual == P2.virtual, path
        return second

    src, io = await cmp_cmd(paths,
                            read_bytes=read_bytes,
                            stdin=stdin,
                            **kwargs)
    out = b"" if src is None else await materialize(src)
    return out.decode(), (io.stderr or b"").decode(), io.exit_code


@pytest.mark.asyncio
async def test_a_dash_operand_reads_stdin_and_is_named_dash():
    assert await _run_with_stdin(
        [DASH, P2], b"one\n",
        b"two\n") == ("- /F/two differ: char 1, line 1\n", "", 1)


@pytest.mark.asyncio
async def test_dev_stdin_reads_stdin_and_is_named_as_typed():
    assert await _run_with_stdin(
        [DEV_STDIN, P2], b"one\n",
        b"two\n") == ("/dev/stdin /F/two differ: char 1, line 1\n", "", 1)


@pytest.mark.asyncio
async def test_a_lone_operand_is_compared_with_stdin():
    out, err, code = await _run_with_stdin([P2], b"ab", b"abc")
    assert (out, code) == ("", 1)
    assert err == "cmp: EOF on - after byte 2, in line 1\n"


@pytest.mark.asyncio
async def test_no_operand_is_gnus_missing_operand_usage_error():
    with pytest.raises(UsageError) as exc:
        await cmp_cmd([], read_bytes=_reader(b"", b""))
    assert str(exc.value) == ("cmp: missing operand after 'cmp'\n"
                              "cmp: Try 'cmp --help' for more information.")
    assert exc.value.exit_code == 2


@pytest.mark.asyncio
async def test_two_stdin_operands_are_one_file_whatever_the_skips():

    async def unread(path: PathSpec) -> bytes:
        raise AssertionError(f"read {path.virtual}")

    src, io = await cmp_cmd([DASH, DEV_STDIN],
                            read_bytes=unread,
                            stdin=b"abc",
                            skip=(0, 1))
    assert (src, io.exit_code, io.stderr) == (None, 0, None)


@pytest.mark.asyncio
async def test_eof_on_a_line_boundary_names_the_line_it_closed():
    _, err, _ = await _run(b"ab\n", b"ab\ncd")
    assert err == "cmp: EOF on /F/one after byte 3, line 1\n"


@pytest.mark.asyncio
@pytest.mark.parametrize("verbose", [False, True])
async def test_eof_on_an_empty_file_says_which_is_empty(verbose):
    _, err, code = await _run(b"", b"x", verbose=verbose)
    assert (err, code) == ("cmp: EOF on /F/one which is empty\n", 1)


@pytest.mark.asyncio
async def test_verbose_pads_offsets_to_the_smaller_regular_file():
    out, _, _ = await _run(b"a" * 11, b"b" + b"a" * 12, verbose=True)
    assert out == " 1 141 142\n"


@pytest.mark.asyncio
async def test_verbose_sizes_the_offsets_by_the_file_not_the_stream():
    out, err, _ = await _run_with_stdin([DASH, P2],
                                        b"hello\nx\n",
                                        b"hello\nworld\nfoo\nbar\nbaz\n",
                                        verbose=True)
    assert out == " 7 170 167\n 8  12 157\n"
    assert err == "cmp: EOF on - after byte 8\n"


@pytest.mark.asyncio
async def test_operands_are_named_as_typed():
    one = PathSpec(virtual="/F/one",
                   directory="/F/",
                   vfs_path="one",
                   raw_path="one")
    two = PathSpec(virtual="/F/two",
                   directory="/F/",
                   vfs_path="two",
                   raw_path="two")
    src, _ = await cmp_cmd([one, two], read_bytes=_reader(b"a", b"b"))
    assert await materialize(src) == b"one two differ: char 1, line 1\n"


@pytest.mark.asyncio
async def test_silent_keeps_exit_2_for_an_operand_it_cannot_read():
    # diffutils 3.10: `cmp -s a.txt nope` prints nothing and exits 2; the
    # message is what -s drops, not the trouble.

    async def missing(path: PathSpec) -> bytes:
        raise FileNotFoundError(path.virtual)

    for silent, want in ((True, ""),
                         (False, "cmp: /F/one: No such file or directory\n")):
        src, io = await cmp_cmd([P1, P2], read_bytes=missing, silent=silent)
        assert src is None
        assert (io.stderr or b"").decode() == want
        assert io.exit_code == 2


def _dirs(*dirs: str):

    async def read(path: PathSpec) -> bytes:
        if path.virtual in dirs:
            raise IsADirectoryError(path.virtual)
        if path.virtual.endswith("nope"):
            raise FileNotFoundError(path.virtual)
        return b"a"

    return read


def _spec(name: str) -> PathSpec:
    return PathSpec(virtual=f"/F/{name}",
                    directory="/F/",
                    vfs_path=name,
                    raw_path=name)


@pytest.mark.asyncio
@pytest.mark.parametrize("names,silent,code,stderr", [
    (("dir", "one"), True, 2, "cmp: dir: Is a directory\n"),
    (("one", "dir"), True, 2, "cmp: dir: Is a directory\n"),
    (("dir", "nope"), True, 2, ""),
    (("dir", "nope"), False, 2, "cmp: nope: No such file or directory\n"),
    (("dir", "dir"), False, 0, ""),
])
async def test_a_directory_fails_at_its_read_after_both_opens(
        names, silent, code, stderr):
    # diffutils 3.10 opens both operands, then reads: -s drops only a
    # failed open, a directory opens and fails reading, and one file
    # named twice at the same offset is equal unread.
    _, io = await cmp_cmd([_spec(n) for n in names],
                          read_bytes=_dirs("/F/dir"),
                          silent=silent)
    assert ((io.stderr or b"").decode(), io.exit_code) == (stderr, code)


def test_parse_flags_reads_the_long_spellings_and_refuses_l_with_s():
    # --quiet and --silent are -s; --verbose is -l, and diffutils refuses
    # the pair while it reads the options.
    assert parse_flags({"quiet": True}).silent
    assert parse_flags({"silent": True}).silent
    assert parse_flags({"verbose": True}).verbose
    with pytest.raises(UsageError) as info:
        parse_flags({"verbose": True, "silent": True})
    assert str(info.value) == ("cmp: options -l and -s are incompatible\n"
                               "cmp: Try 'cmp --help' for more information.")
