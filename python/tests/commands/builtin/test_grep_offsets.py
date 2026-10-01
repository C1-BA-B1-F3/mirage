import re

import pytest

from mirage.commands.builtin.grep_offsets import (
    MatchOffsets,
    decode_line,
    encode_line,
    line_offsets,
    match_offset,
    prefix_of,
    rg_pieces,
    rust_matches,
)


def test_line_offsets_count_the_stripped_terminator():
    # abc\ndefabc\nabc abc\n -- section Q1 of the GNU truth file.
    assert line_offsets(["abc", "defabc", "abc abc"]) == [0, 4, 11]


def test_line_offsets_count_bytes_not_characters():
    # `caf` + U+00E9 (two bytes) + a space is six bytes, so line two starts
    # at 10 rather than at the character index 9.
    assert line_offsets(["café abc", "xéy abc"]) == [0, 10]


def test_line_offsets_do_not_read_past_the_last_line():
    # A file with no final newline still reports 0 for its one line; the
    # extra byte the accumulator adds is never read.
    assert line_offsets(["no-newline-abc"]) == [0]


def test_line_offsets_of_no_lines_is_empty():
    assert line_offsets([]) == []


def test_match_offset_adds_the_line_start_in_bytes():
    assert match_offset(10, "xéy abc", 4) == 15


def test_match_offset_at_the_start_of_a_line_is_the_line_start():
    assert match_offset(11, "abc abc", 0) == 11


def test_prefix_of_puts_the_line_number_before_the_byte_offset():
    assert prefix_of(2, 4) == "2:4:"


def test_prefix_of_omits_a_field_that_is_off():
    assert (prefix_of(2, None), prefix_of(None, 4)) == ("2:", "4:")


def test_prefix_of_is_empty_when_neither_flag_is_set():
    assert prefix_of(None, None) == ""


def test_prefix_of_renders_a_context_line_with_dashes_throughout():
    assert prefix_of(3, 12, False) == "3-12-"


def test_decode_line_carries_one_invalid_byte_as_one_character():
    # A replacing decode reads 0xff as U+FFFD, which is three bytes wide,
    # so every offset past it ran ahead of GNU's.
    assert decode_line(b"\xffa") == "\udcffa"


def test_decode_line_leaves_valid_utf8_alone():
    assert decode_line("café abc".encode()) == "café abc"


def test_encode_line_round_trips_decode_line():
    raw = b"\xffa\xc3\xa9\xfe"
    assert encode_line(decode_line(raw)) == raw


def test_line_offsets_are_exact_over_an_invalid_byte():
    # `\xff` is one byte, so the second line starts at 2 -- GNU's answer for
    # `grep -b a` over `\xff\na\n`, where a replacing decode said 4.
    assert line_offsets([decode_line(b"\xff"), "a"]) == [0, 2]


def test_match_offset_counts_an_invalid_byte_as_one():
    # `grep -bo a` over `\xffa\n` is `1:a` on GNU grep 3.11.
    assert match_offset(0, decode_line(b"\xffa"), 1) == 1


def test_incremental_offsets_preserve_unicode_and_escaped_bytes():
    offsets = MatchOffsets(10, "é😀a\udcffé😀a")
    assert [offsets.at(2), offsets.at(6)] == [16, 24]


@pytest.mark.parametrize(
    "raw,expected",
    [
        (b"\xef\xbb\xbfa", "\ufeffa"),
        (b"\xc0\xaf\xc1\xbf", "\udcc0\udcaf\udcc1\udcbf"),
        (b"\xe0\x80\x80\xed\xa0\x80", "\udce0\udc80\udc80\udced\udca0\udc80"),
        (b"\xf0\x80\x80\x80", "\udcf0\udc80\udc80\udc80"),
        (b"\xf4\x90\x80\x80\xf5\xff", "\udcf4\udc90\udc80\udc80\udcf5\udcff"),
        (
            b"\xc2A\xe1\x80B\xf0\x90\x80",
            "\udcc2A\udce1\udc80B\udcf0\udc90\udc80",
        ),
        (
            b"\xef\xbb\xbf\xff\xc2\x80\xe0\xa0\x80\xed\x9f\xbf\xf0\x90\x82\x80\xf4\x8f\xbf\xbf",
            "\ufeff\udcff\u0080\u0800\ud7ff𐂀\U0010ffff",
        ),
    ],
)
def test_decode_utf8_boundaries_without_replacing_bytes(raw, expected):
    assert decode_line(raw) == expected
    assert encode_line(decode_line(raw)) == raw


def test_decode_large_malformed_line():
    expected = ("x" * 8190 + "𐂀\udcffé") * 4
    assert decode_line(encode_line(expected)) == expected


def test_rust_matches_resume_one_character_after_an_empty_match():
    # `rg -o 'x*'` over `abc` prints four empty lines on ripgrep 14.1.1.
    assert rust_matches(re.compile("x*"), "abc") == [
        (0, ""),
        (1, ""),
        (2, ""),
        (3, ""),
    ]


def test_rust_matches_skip_an_empty_match_where_a_match_ended():
    # `rg -o 'b*'` over `abc` is an empty line, `b`, an empty line, where
    # finditer also finds the empty match at 2.
    assert rust_matches(re.compile("b*"), "abc") == [
        (0, ""),
        (1, "b"),
        (3, ""),
    ]


def test_rust_matches_skip_it_after_every_non_empty_match():
    # `rg -o '[0-9]*'` over `1a22b` prints `1`, `22` and an empty line.
    assert rust_matches(re.compile("[0-9]*"), "1a22b") == [
        (0, "1"),
        (2, "22"),
        (5, ""),
    ]


def test_rust_matches_take_the_first_alternative_that_matches():
    # `rg -o 'o|'` over `foo` is an empty line, `o`, `o`.
    assert rust_matches(re.compile("o|"), "foo") == [
        (0, ""),
        (1, "o"),
        (2, "o"),
    ]


def test_rust_matches_see_the_text_before_where_they_resume():
    # `rg -o '\b'` over `ab` is two empty lines: no boundary inside `ab`.
    assert rust_matches(re.compile(r"\b"), "ab") == [(0, ""), (2, "")]


def test_rust_matches_anchor_only_at_the_line_start():
    # `rg -o '^'` over `ab` is one empty line.
    assert rust_matches(re.compile("^"), "ab") == [(0, "")]


def test_rust_matches_step_over_a_character_not_a_byte():
    assert rust_matches(re.compile("x*"), "é😀") == [(0, ""), (1, ""), (2, "")]


def test_rust_matches_of_no_match_is_empty():
    assert rust_matches(re.compile("y"), "x") == []


def test_rg_pieces_are_the_matches_when_there_are_any():
    assert rg_pieces(re.compile("[0-9]"), "a1b2c") == [(1, "1"), (3, "2")]


def test_rg_pieces_print_a_line_without_a_match_whole():
    # `rg -ov y` over `x` prints `x`, as a context line under -o prints.
    assert rg_pieces(re.compile("y"), "x") == [(0, "x")]
