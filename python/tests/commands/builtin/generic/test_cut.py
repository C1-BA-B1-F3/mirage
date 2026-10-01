import pytest

from mirage.commands.builtin.generic.cut import cut, parse_flags
from mirage.io.types import materialize


def _unused_read_stream(_path):
    raise AssertionError("read_stream should not be called for stdin input")


def test_multi_char_delimiter_is_rejected():
    with pytest.raises(
        ValueError, match="delimiter must be a single character"
    ):
        parse_flags({"delimiter": ",,", "fields": "1"})


def test_single_char_delimiter_is_accepted():
    parsed = parse_flags({"delimiter": ",", "fields": "1"})
    assert parsed.delimiter == ","


@pytest.mark.asyncio
async def test_multi_char_delimiter_exits_one():
    source, io = await cut(
        [],
        read_stream=_unused_read_stream,
        stdin=b"a,b\n",
        flags={"delimiter": ",,", "fields": "1"},
    )

    assert source is None
    assert io.exit_code == 1
    assert b"delimiter must be a single character" in await materialize(
        io.stderr
    )


_TRY = b"Try 'cut --help' for more information.\n"

# Measured against GNU coreutils 9.4 on `printf 'a,b,c\n'`.
_GNU_REFUSALS = [
    ({"delimiter": ",", "fields": "2-3x"}, b"cut: invalid field value 'x'\n"),
    ({"delimiter": ",", "fields": "abc"}, b"cut: invalid field value 'abc'\n"),
    ({"characters": "abc"}, b"cut: invalid byte/character position 'abc'\n"),
    ({"delimiter": ",", "fields": "0"}, b"cut: fields are numbered from 1\n"),
    ({"delimiter": ",", "fields": "3-1"}, b"cut: invalid decreasing range\n"),
    ({"delimiter": ",", "fields": ""}, b"cut: fields are numbered from 1\n"),
    ({"delimiter": ",", "fields": "1,2x"}, b"cut: invalid field value 'x'\n"),
    ({"delimiter": ",", "fields": "2 "}, b"cut: fields are numbered from 1\n"),
    ({"delimiter": ",", "fields": "1-2-3"}, b"cut: invalid field range\n"),
]


@pytest.mark.parametrize("flags,message", _GNU_REFUSALS)
@pytest.mark.asyncio
async def test_bad_range_exits_one_with_two_stderr_lines(flags, message):
    source, io = await cut(
        [],
        read_stream=_unused_read_stream,
        stdin=b"a,b,c\n",
        flags=flags,
    )

    assert source is None
    assert io.exit_code == 1
    assert await materialize(io.stderr) == message + _TRY


@pytest.mark.parametrize(
    "flags,expected",
    [
        ({"delimiter": ",", "fields": "2-"}, b"b,c\n"),
        ({"delimiter": ",", "fields": "-2"}, b"a,b\n"),
        ({"characters": "2-"}, b",b,c\n"),
    ],
)
@pytest.mark.asyncio
async def test_open_ended_ranges_stay_valid(flags, expected):
    """GNU exits 0 for `2-`, `-2` and `-c 2-`.

    A too-strict scan fails loudly here rather than silently refusing
    input GNU accepts.
    """
    source, io = await cut(
        [],
        read_stream=_unused_read_stream,
        stdin=b"a,b,c\n",
        flags=flags,
    )

    assert io.exit_code == 0
    assert await materialize(source) == expected


# `--whitespace-delimited` has one candidate, so ARGMATCH accepts any
# prefix of it. The refusal keeps cut's own one-line wording; GNU cut has
# no such option, so the rows below are the general rule's answer rather
# than a measured one, and the empty word (which the general rule
# ACCEPTS against a sole candidate) is deliberately not pinned either
# way.
@pytest.mark.parametrize("value", ["trimmed", "trim", "t"])
def test_whitespace_delimited_accepts_an_unambiguous_prefix(value):
    assert (
        parse_flags({"fields": "1", "whitespace_delimited": value}).whitespace
        == "trimmed"
    )


def test_whitespace_delimited_still_refuses_an_unmatched_word():
    with pytest.raises(ValueError) as exc:
        parse_flags({"fields": "1", "whitespace_delimited": "tt"})
    assert str(exc.value) == (
        "cut: invalid argument 'tt' for '--whitespace-delimited'"
    )
