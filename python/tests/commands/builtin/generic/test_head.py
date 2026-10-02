import pytest

from mirage.commands.builtin.generic.head import head


async def _drain(gen):
    return b"".join([c async for c in gen])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "chunks,flags,expected",
    [
        ([b"hel", b"lo wor", b"ld"], {"c": 8}, b"hello wo"),
        ([b"a\nb", b"\nc\nd\n"], {"n": 2}, b"a\nb\n"),
    ],
)
async def test_head_reads_across_chunks(chunks, flags, expected):

    async def src():
        for chunk in chunks:
            yield chunk

    assert await _drain(head(src(), **flags)) == expected


@pytest.mark.asyncio
async def test_head_first_c_bytes_shorter_than_total():
    out = await _drain(head(b"hi", c=100))
    assert out == b"hi"


@pytest.mark.asyncio
async def test_head_first_c_zero_emits_nothing():
    out = await _drain(head(b"hello", c=0))
    assert out == b""


@pytest.mark.asyncio
async def test_head_default_n_is_10():
    body = b"".join(f"line{i}\n".encode() for i in range(1, 15))
    out = await _drain(head(body))
    lines = out.decode().splitlines()
    assert len(lines) == 10
    assert lines[0] == "line1"
    assert lines[9] == "line10"


@pytest.mark.asyncio
async def test_head_n_zero_emits_nothing():
    out = await _drain(head(b"a\nb\n", n=0))
    assert out == b""


@pytest.mark.asyncio
async def test_head_negative_n_excludes_last_n_lines():
    out = await _drain(head(b"a\nb\nc\nd\n", n=-1))
    assert out == b"a\nb\nc\n"


@pytest.mark.asyncio
async def test_head_negative_n_equal_to_total_emits_nothing():
    out = await _drain(head(b"a\nb\n", n=-2))
    assert out == b""


@pytest.mark.asyncio
async def test_head_stops_consuming_stream_after_n_lines():
    consumed = []

    async def src():
        for line in [b"a\n", b"b\n", b"c\n", b"d\n", b"e\n"]:
            consumed.append(line)
            yield line

    chunks = [c async for c in head(src(), n=2)]
    assert b"".join(chunks) == b"a\nb\n"
    assert consumed == [b"a\n", b"b\n"]


@pytest.mark.asyncio
async def test_head_no_trailing_newline_in_last_line():
    out = await _drain(head(b"a\nb\nno-end", n=3))
    assert out == b"a\nb\nno-end"


@pytest.mark.asyncio
async def test_head_empty_input_with_c():
    out = await _drain(head(b"", c=10))
    assert out == b""


@pytest.mark.asyncio
async def test_head_single_line_no_newline_default_n():
    """head on a single line without trailing newline returns it as-is."""
    out = await _drain(head(b"hello"))
    assert out == b"hello"
