import pytest

from mirage.commands.builtin.generic.cut import cut, parse_flags


def test_multi_char_delimiter_is_rejected():
    with pytest.raises(
        ValueError, match="delimiter must be a single character"
    ):
        parse_flags({"delimiter": ",,", "fields": "1"})


def test_single_char_delimiter_is_accepted():
    parsed = parse_flags({"delimiter": ",", "fields": "1"})
    assert parsed.delimiter == ","


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


async def _no_stream(_path):
    raise AssertionError("cut read with no operand")
    yield b""


@pytest.mark.asyncio
async def test_cut_missing_operand():
    with pytest.raises(ValueError, match="missing operand"):
        await cut([], read_stream=_no_stream, flags={"fields": "1"})
