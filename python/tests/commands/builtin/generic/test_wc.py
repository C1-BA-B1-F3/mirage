import pytest

from mirage.commands.builtin.generic.wc import (WCCounts, format_multi,
                                                format_wc_lines, number_width,
                                                parse_flags, wc)
from mirage.commands.errors import UsageError
from mirage.types import PathSpec


@pytest.mark.asyncio
async def test_wc_default_counts_bytes():
    counts = await wc(b"hello world\nfoo bar\n")
    assert counts.lines == 2
    assert counts.words == 4
    assert counts.bytes_ == 20
    assert counts.chars == 20


@pytest.mark.asyncio
async def test_wc_empty_input():
    counts = await wc(b"")
    assert counts == WCCounts(lines=0,
                              words=0,
                              bytes_=0,
                              chars=0,
                              max_line_length=0)


@pytest.mark.asyncio
async def test_wc_lines_with_trailing_newline():
    counts = await wc(b"a\nb\nc\n")
    assert counts.lines == 3


@pytest.mark.asyncio
async def test_wc_lines_without_trailing_newline():
    """POSIX: lines = number of \\n bytes. `a\\nb\\nc` has 2 newlines."""
    counts = await wc(b"a\nb\nc")
    assert counts.lines == 2


@pytest.mark.asyncio
async def test_wc_words_single_line():
    counts = await wc(b"one two three")
    assert counts.words == 3


@pytest.mark.asyncio
async def test_wc_words_multiline():
    counts = await wc(b"one two\nthree four five\nsix\n")
    assert counts.words == 6


@pytest.mark.asyncio
async def test_wc_words_leading_trailing_whitespace():
    """POSIX: leading/trailing whitespace doesn't add words."""
    counts = await wc(b"   hello   world   ")
    assert counts.words == 2


@pytest.mark.asyncio
async def test_wc_words_only_whitespace():
    counts = await wc(b"   \t  \n  ")
    assert counts.words == 0


@pytest.mark.asyncio
async def test_wc_bytes_ascii():
    counts = await wc(b"hello")
    assert counts.bytes_ == 5
    assert counts.chars == 5


@pytest.mark.asyncio
async def test_wc_chars_vs_bytes_multibyte_utf8():
    """`café` is 4 chars / 5 bytes (é is 2 bytes in UTF-8)."""
    data = "café".encode()
    counts = await wc(data)
    assert counts.bytes_ == 5
    assert counts.chars == 4


@pytest.mark.asyncio
async def test_wc_chars_vs_bytes_pure_multibyte():
    data = "ééé".encode()
    counts = await wc(data)
    assert counts.bytes_ == 6
    assert counts.chars == 3


@pytest.mark.asyncio
async def test_wc_max_line_length_empty():
    counts = await wc(b"")
    assert counts.max_line_length == 0


@pytest.mark.asyncio
async def test_wc_max_line_length_single_line_with_newline():
    counts = await wc(b"hello\n")
    assert counts.max_line_length == 5


@pytest.mark.asyncio
async def test_wc_max_line_length_picks_longest():
    counts = await wc(b"short\na much longer line\nmed\n")
    assert counts.max_line_length == len(b"a much longer line")


@pytest.mark.asyncio
async def test_wc_max_line_length_no_trailing_newline():
    counts = await wc(b"hello world")
    assert counts.max_line_length == 11


@pytest.mark.asyncio
async def test_wc_streams_chunked():
    """Streaming through chunk boundaries gives same counts as buffered."""

    async def src():
        yield b"hello "
        yield b"world\n"
        yield b"foo bar\n"

    counts = await wc(src())
    assert counts.lines == 2
    assert counts.words == 4
    assert counts.bytes_ == 20


@pytest.mark.asyncio
async def test_wc_word_split_across_chunks():
    """A word straddling a chunk boundary still counts as one word."""

    async def src():
        yield b"hel"
        yield b"lo"
        yield b" world\n"

    counts = await wc(src())
    assert counts.words == 2
    assert counts.lines == 1


@pytest.mark.asyncio
async def test_wc_utf8_split_across_chunks_does_not_lose_chars():
    """A multibyte UTF-8 sequence split across chunks must still decode."""

    async def src():
        # é = b"\xc3\xa9" — split between the two bytes
        yield b"caf\xc3"
        yield b"\xa9"

    counts = await wc(src())
    assert counts.bytes_ == 5
    assert counts.chars == 4


@pytest.mark.asyncio
async def test_wc_byte_by_byte_chunking():
    """Worst-case chunking: every byte its own chunk."""

    async def src():
        for byte in b"hello world\nfoo bar\n":
            yield bytes([byte])

    counts = await wc(src())
    assert counts.lines == 2
    assert counts.words == 4
    assert counts.bytes_ == 20


@pytest.mark.asyncio
async def test_wc_binary_input_does_not_crash():
    """`errors='replace'` must let arbitrary bytes pass — count bytes
    accurately even when UTF-8 decoding produces replacement chars."""
    data = bytes(range(256))
    counts = await wc(data)
    assert counts.bytes_ == 256
    assert counts.lines == 1  # one \n at byte 0x0a


def _fmt(counts, **kw):
    label = kw.pop("label", None)
    return format_wc_lines([(counts, label)], **kw)[0]


def test_format_wc_lines_default_no_label():
    counts = WCCounts(lines=2, words=4, bytes_=20)
    assert _fmt(counts) == "      2       4      20"


def test_format_wc_lines_default_with_label():
    counts = WCCounts(lines=2, words=4, bytes_=20)
    assert _fmt(counts, label="/f.txt") == " 2  4 20 /f.txt"


def test_format_wc_lines_args_l():
    counts = WCCounts(lines=2, words=4, bytes_=20)
    assert _fmt(counts, lines=True) == "2"
    assert _fmt(counts, lines=True, label="/f.txt") == "2 /f.txt"


def test_format_wc_lines_quotes_only_a_name_holding_a_newline():
    # coreutils 9.7 wc.c: `strchr (file, '\n') ? quotef (file) : file`.
    counts = WCCounts(lines=2)
    assert _fmt(counts, lines=True, label="/a/n\nq") == "2 '/a/n'$'\\n''q'"
    assert _fmt(counts, lines=True, label="/a/b c") == "2 /a/b c"


def test_format_wc_lines_w_c_m():
    counts = WCCounts(lines=2, words=4, bytes_=20, chars=18)
    assert _fmt(counts, words=True) == "4"
    assert _fmt(counts, bytes_=True) == "20"
    assert _fmt(counts, chars=True) == "18"


def test_format_wc_lines_combines_lines_and_max_line_length():
    counts = WCCounts(lines=2, max_line_length=11)
    assert _fmt(counts, lines=True, max_line_length=True) == "      2      11"


def test_format_wc_lines_combines_selected_counts_in_canonical_order():
    counts = WCCounts(lines=2, words=4, bytes_=20, chars=18)
    assert _fmt(counts, lines=True, words=True, bytes_=True,
                chars=True) == "      2       4      18      20"


def test_wc_counts_merge():
    a = WCCounts(lines=2, words=4, bytes_=20, chars=18, max_line_length=11)
    b = WCCounts(lines=1, words=2, bytes_=8, chars=8, max_line_length=20)
    a.merge(b)
    assert a.lines == 3
    assert a.words == 6
    assert a.bytes_ == 28
    assert a.chars == 26
    assert a.max_line_length == 20


@pytest.mark.asyncio
async def test_format_multi_single_path_emits_trailing_newline():
    paths = [PathSpec.from_str_path("/a.txt")]

    async def fake_read(_path):
        return b"hello\n"

    out, err = await format_multi(paths, read=fake_read, lines=True)
    assert out == b"1 /a.txt\n"
    assert err == b""


@pytest.mark.asyncio
async def test_format_multi_multi_path_emits_total_and_trailing_newline():
    paths = [
        PathSpec.from_str_path("/a.txt"),
        PathSpec.from_str_path("/b.txt"),
    ]
    data = {"/a.txt": b"hello\n", "/b.txt": b"world\nworld\n"}

    async def fake_read(path):
        return data[path.virtual]

    out, err = await format_multi(paths, read=fake_read, lines=True)
    assert err == b""
    assert out.endswith(b"\n")
    lines = out.decode().rstrip("\n").split("\n")
    # GNU pads to the digits of the files' 18 bytes, not the widest count.
    assert lines == [" 1 /a.txt", " 2 /b.txt", " 3 total"]


@pytest.mark.asyncio
async def test_format_multi_accepts_sync_read_returning_bytes():
    paths = [PathSpec.from_str_path("/a.txt")]

    def sync_read(_path):
        return b"x\n"

    out, err = await format_multi(paths, read=sync_read, lines=True)
    assert out == b"1 /a.txt\n"
    assert err == b""


@pytest.mark.asyncio
async def test_format_multi_empty_paths_returns_empty():

    async def fake_read(_path):
        return b""

    out, err = await format_multi([], read=fake_read, lines=True)
    assert out == b""
    assert err == b""


@pytest.mark.asyncio
async def test_format_multi_missing_operand_reports_and_totals():
    paths = [
        PathSpec.from_str_path("/a.txt"),
        PathSpec.from_str_path("/m.txt"),
    ]

    async def fake_read(path):
        if path.virtual == "/m.txt":
            raise FileNotFoundError(path.virtual)
        return b"hello\n"

    out, err = await format_multi(paths, read=fake_read, lines=True)
    assert out == b"1 /a.txt\n1 total\n"
    assert err == b"wc: /m.txt: No such file or directory\n"


@pytest.mark.asyncio
async def test_format_multi_all_missing_zero_total():
    paths = [
        PathSpec.from_str_path("/m1.txt"),
        PathSpec.from_str_path("/m2.txt"),
    ]

    async def fake_read(path):
        raise FileNotFoundError(path.virtual)

    out, err = await format_multi(paths, read=fake_read, lines=True)
    assert out == b"0 total\n"
    assert err == (b"wc: /m1.txt: No such file or directory\n"
                   b"wc: /m2.txt: No such file or directory\n")


async def _async_byte_read(_path):
    yield b"hello "
    yield b"world\n"


@pytest.mark.asyncio
async def test_format_multi_accepts_async_iterator_read():
    paths = [PathSpec.from_str_path("/a.txt")]

    out, err = await format_multi(paths, read=_async_byte_read, lines=True)
    assert out == b"1 /a.txt\n"
    assert err == b""


# GNU's ARGMATCH refusal names the refused word through gnulib's quote(),
# so a byte outside 0x20-0x7e comes back escaped. Rows measured against
# GNU coreutils 9.4 under `LC_ALL=C` with a raw `bytes` argv
# (`wc --total=<w>`). Mirrored in wc.test.ts.
@pytest.mark.parametrize("value,escaped", [
    ("xé", r"x\303\251"),
    ("x\r", r"x\r"),
    ("x\x01", r"x\001"),
    ("x\x7f", r"x\177"),
    ("x'", r"x\'"),
    ("x\\", r"x\\"),
])
def test_total_refusal_quotes_the_word(value, escaped):
    with pytest.raises(UsageError) as exc:
        parse_flags({"total": value})
    assert str(exc.value).startswith(
        f"wc: invalid argument '{escaped}' for '--total'\n")


def test_total_refusal_carries_gnus_candidate_block_and_exit_1():
    """Measured, coreutils 9.4: `wc --total=x f` lists all four modes."""
    with pytest.raises(UsageError) as exc:
        parse_flags({"total": "x"})
    assert str(exc.value) == ("wc: invalid argument 'x' for '--total'\n"
                              "Valid arguments are:\n"
                              "  - 'auto'\n  - 'always'\n"
                              "  - 'only'\n  - 'never'\n"
                              "Try 'wc --help' for more information.")
    assert exc.value.exit_code == 1


def test_an_empty_total_is_ambiguous_not_the_default():
    """`wc --total=` is `ambiguous argument ''`, exit 1 (measured).

    python used to read the empty word as the `auto` default and exit 0
    through an `or "auto"` fallback, which was also the one py/ts split
    at this slot -- TypeScript refused it.
    """
    with pytest.raises(UsageError) as exc:
        parse_flags({"total": ""})
    assert str(
        exc.value).startswith("wc: ambiguous argument '' for '--total'\n")
    assert exc.value.exit_code == 1


def test_an_absent_total_is_still_auto():
    assert parse_flags({}).total == "auto"


# `wc --total=al` is `always` and `--total=au` is `auto` (measured,
# coreutils 9.4), while the bare `a` they share spans two values.
def test_total_accepts_an_unambiguous_prefix():
    assert parse_flags({"total": "al"}).total == "always"
    assert parse_flags({"total": "au"}).total == "auto"
    assert parse_flags({"total": "o"}).total == "only"
    assert parse_flags({"total": "n"}).total == "never"
    assert parse_flags({"total": "always"}).total == "always"


def test_total_refuses_a_prefix_spanning_two_values():
    with pytest.raises(UsageError) as exc:
        parse_flags({"total": "a"})
    assert str(exc.value) == ("wc: ambiguous argument 'a' for '--total'\n"
                              "Valid arguments are:\n"
                              "  - 'auto'\n  - 'always'\n"
                              "  - 'only'\n  - 'never'\n"
                              "Try 'wc --help' for more information.")
    assert exc.value.exit_code == 1


@pytest.mark.parametrize("sizes,operands,counts,width", [
    ([24], 1, 1, 1),
    ([24], 1, 3, 2),
    ([24, 6], 2, 1, 2),
    ([0, 0], 2, 3, 1),
    ([None], 1, 3, 7),
    ([None], 1, 1, 1),
    ([None, 24], 2, 1, 7),
    ([123456789], 2, 1, 9),
])
def test_number_width_follows_the_operands(sizes, operands, counts, width):
    # coreutils 9.7: one operand with one count is unpadded; otherwise the
    # regular files' total size, at least 7 beside a stream or directory.
    assert number_width(sizes, operands, counts) == width


@pytest.mark.asyncio
async def test_format_multi_sizes_columns_by_the_files():
    paths = [PathSpec.from_str_path("/a.txt")]

    async def fake_read(_path):
        return b"hello\nworld\nfoo\nbar\nbaz\n"

    out, _ = await format_multi(paths, read=fake_read, lines=True, words=True)
    assert out == b" 5  5 /a.txt\n"


@pytest.mark.asyncio
async def test_format_multi_prints_zeros_for_a_directory_and_pads_to_seven():
    paths = [PathSpec.from_str_path("/sub"), PathSpec.from_str_path("/a.txt")]

    async def fake_read(path):
        if path.virtual == "/sub":
            raise IsADirectoryError(21, "Is a directory", path.virtual)
        return b"hello\n"

    out, err = await format_multi(paths, read=fake_read)
    assert out == (b"      0       0       0 /sub\n"
                   b"      1       1       6 /a.txt\n"
                   b"      1       1       6 total\n")
    assert err == b"wc: /sub: Is a directory\n"
