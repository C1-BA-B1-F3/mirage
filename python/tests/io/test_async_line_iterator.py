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

from mirage.io.async_line_iterator import AsyncLineIterator, char_width


async def _chunks(parts: list[bytes]):
    for p in parts:
        yield p


@pytest.mark.asyncio
async def test_clean_boundaries():
    source = _chunks([b"hello\nworld\n"])
    lines = [line async for line in AsyncLineIterator(source)]
    assert lines == [b"hello", b"world"]


@pytest.mark.asyncio
async def test_split_across_chunks():
    source = _chunks([b"hel", b"lo\nwor", b"ld\n"])
    lines = [line async for line in AsyncLineIterator(source)]
    assert lines == [b"hello", b"world"]


@pytest.mark.asyncio
async def test_no_trailing_newline():
    source = _chunks([b"hello\nworld"])
    lines = [line async for line in AsyncLineIterator(source)]
    assert lines == [b"hello", b"world"]


@pytest.mark.asyncio
async def test_empty_input():
    source = _chunks([])
    lines = [line async for line in AsyncLineIterator(source)]
    assert lines == []


@pytest.mark.asyncio
async def test_empty_chunk():
    source = _chunks([b"", b"hello\n", b""])
    lines = [line async for line in AsyncLineIterator(source)]
    assert lines == [b"hello"]


@pytest.mark.asyncio
async def test_single_large_line():
    big = b"x" * 100000 + b"\n"
    source = _chunks([big[:8192], big[8192:]])
    lines = [line async for line in AsyncLineIterator(source)]
    assert lines == [b"x" * 100000]


@pytest.mark.asyncio
async def test_many_lines_one_chunk():
    source = _chunks([b"a\nb\nc\nd\n"])
    lines = [line async for line in AsyncLineIterator(source)]
    assert lines == [b"a", b"b", b"c", b"d"]


@pytest.mark.asyncio
async def test_early_termination():
    pull_count = 0

    async def _counting_chunks():
        nonlocal pull_count
        for i in range(1000):
            pull_count += 1
            yield f"line{i}\n".encode()

    lines = []
    async for line in AsyncLineIterator(_counting_chunks()):
        lines.append(line)
        if len(lines) >= 3:
            break
    assert len(lines) == 3
    assert pull_count < 10


def test_char_width_steps_one_utf8_character_at_a_time():
    assert char_width(b"a") == 1
    assert char_width("é".encode()) == 2
    assert char_width("€".encode()) == 3
    assert char_width("😀".encode()) == 4
    # Bytes that decode to one replacement character each: a stray
    # continuation byte, a lead the encoding never uses, and a sequence
    # cut short by a byte that cannot continue it.
    assert char_width(b"\x80") == 1
    assert char_width(b"\xff") == 1
    assert char_width(b"\xe0A") == 1
    assert char_width(b"\xe0\xa0A") == 2
    # Never past the end of what is there.
    assert char_width("é".encode()[:1]) == 1


@pytest.mark.asyncio
async def test_read_chars_counts_characters_not_bytes():
    """`read -n 1` on `éx` takes `é` and leaves `x`, as bash does in a
    UTF-8 locale; counting bytes would split the character and leave
    the other half to corrupt the next read."""
    it = AsyncLineIterator(_chunks(["éx".encode()]))
    first, complete = await it.read_chars(1, b"\n")
    assert (first.decode(), complete) == ("é", True)
    second, complete = await it.read_chars(1, b"\n")
    assert (second.decode(), complete) == ("x", True)


@pytest.mark.asyncio
async def test_read_chars_spanning_a_chunk_boundary():
    it = AsyncLineIterator(_chunks([b"\xc3", b"\xa9x"]))
    data, complete = await it.read_chars(2, None)
    assert (data.decode(), complete) == ("éx", True)


@pytest.mark.asyncio
async def test_read_chars_stops_at_the_delimiter():
    it = AsyncLineIterator(_chunks([b"ab:cd"]))
    data, complete = await it.read_chars(4, b":")
    assert (data, complete) == (b"ab", True)


@pytest.mark.asyncio
async def test_read_chars_reports_a_short_read_at_eof():
    it = AsyncLineIterator(_chunks([b"ab"]))
    data, complete = await it.read_chars(5, None)
    assert (data, complete) == (b"ab", False)


@pytest.mark.asyncio
async def test_skip_only_buffered_empty_lines_with_limit():
    reader = AsyncLineIterator(_chunks([b"\n\n\nx\n\n", b"\nend"]))
    assert reader.skip_empty_lines() == 0
    assert await reader.readline() == b""
    assert reader.skip_empty_lines(0) == 0
    assert reader.skip_empty_lines(1) == 1
    assert reader.skip_empty_lines() == 1
    assert await reader.readline() == b"x"
    assert reader.skip_empty_lines() == 1
    assert reader.skip_empty_lines() == 0
    assert await reader.readline() == b""
    assert await reader.readline() == b"end"
    assert reader.skip_empty_lines() == 0
    assert await reader.readline() is None


@pytest.mark.asyncio
async def test_skip_nonmatching_lines_retains_candidates_across_chunks():
    chunks = [b"first\nskip\nskip\nneedle\nskip\nnee", b"dle\ntail"]

    async def source():
        for chunk in chunks:
            yield chunk

    lines = AsyncLineIterator(source())
    assert lines.skip_nonmatching_lines(b"needle") == (0, 0)
    assert await lines.readline() == b"first"
    assert lines.skip_nonmatching_lines(b"needle") == (2, 10)
    assert lines.skip_nonmatching_lines(b"needle") == (0, 0)
    assert await lines.readline() == b"needle"
    assert lines.skip_nonmatching_lines(b"needle") == (1, 5)
    assert await lines.readline() == b"needle"
    assert lines.skip_nonmatching_lines(b"needle") == (0, 0)
    assert await lines.readline() == b"tail"
    assert await lines.readline() is None
