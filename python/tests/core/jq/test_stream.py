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

import math

import pytest

from mirage.core.jq.stream import (READ_CHUNK, InputReader, is_jsonl_path,
                                   parse_value, pieces_through, read_values)
from mirage.core.jq.types import NO_VALUE, InputSource, JqOptions, JqParseError


async def _chunks(data: bytes, size: int):
    for at in range(0, len(data), size):
        yield data[at:at + size]


def _sources(*inputs: bytes, size: int = 1 << 20) -> list[InputSource]:
    return [
        InputSource(f"f{i}.json", _chunks(data, size))
        for i, data in enumerate(inputs)
    ]


async def _read(
    sources: list[InputSource], opts: JqOptions = JqOptions()) -> list[tuple]:
    reader = InputReader(sources, opts)
    out: list[tuple] = []
    while True:
        value = await reader.next_input()
        if value is NO_VALUE:
            return out
        if isinstance(value, JqParseError):
            out.append(("error", value.message, reader.position()))
            if not opts.seq:
                return out
            continue
        out.append((value, reader.position()))


async def _values(*inputs: bytes, opts: JqOptions = JqOptions()) -> list:
    return [row[0] for row in await _read(_sources(*inputs), opts)]


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [1, 3, 1 << 20])
async def test_the_inputs_are_one_stream_for_one_parser(size):
    # A value runs on from one input into the next (pinned: `12`).
    assert [row[0]
            for row in await _read(_sources(b"1", b"2", size=size))] == [12]
    assert [row[0] for row in await _read(_sources(b"[1,", b"2]", size=size))
            ] == [[1, 2]]


@pytest.mark.asyncio
async def test_a_value_is_placed_where_the_reader_holds_it_whole():
    # `1` completes at the space the second input starts with, by when
    # the reader has opened that input and read its first line.
    assert await _read(_sources(b"1", b" 2\n")) == [(1, "f1.json:1"),
                                                    (2, "f1.json:1")]
    assert await _read(_sources(b"1\n", b"2\n3")) == [(1, "f0.json:1"),
                                                      (2, "f1.json:1"),
                                                      (3, "f1.json:1")]
    assert await _read(_sources(b"1\n2\n",
                                b"[3,\n4]\n5")) == [(1, "f0.json:1"),
                                                    (2, "f0.json:2"),
                                                    ([3, 4], "f1.json:2"),
                                                    (5, "f1.json:2")]


def _lines_before(rows: list[tuple], count: int) -> tuple[int, int]:
    lines = [int(position.rsplit(":", 1)[1]) for _, position in rows[:count]]
    return lines.count(0), lines.count(1)


@pytest.mark.asyncio
async def test_a_long_line_counts_once_the_reader_holds_its_last_piece():
    # jq 1.8.2 reads a long line 4091 bytes at a time: of 4095 values on
    # one 8190-byte line, only the last four arrive with its newline.
    rows = await _read(_sources(b"1 " * 4095 + b"\n2\n"))
    assert _lines_before(rows, 4095) == (4091, 4)


@pytest.mark.asyncio
async def test_a_piece_reads_on_to_the_end_of_a_character():
    # The first piece ends inside an é, reads one more byte to finish it,
    # and so every later piece starts a byte on (pinned: 2044 and 56).
    text = ('"a' + "é" * 2045 + '"  ' + "1 " * 2100 + "\n").encode()
    rows = await _read(_sources(text))
    assert _lines_before(rows[1:], 2100) == (2044, 56)


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [1, 5, 1 << 20])
async def test_json_lines_read_one_line_at_a_time(size):
    data = b'{"a":1}\n{"a":2}\n\n{"a":3}\n'
    assert await _read(_sources(data, size=size)) == [({
        "a": 1
    }, "f0.json:1"), ({
        "a": 2
    }, "f0.json:2"), ({
        "a": 3
    }, "f0.json:4")]


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [1, 5, 1 << 20])
async def test_a_pretty_printed_document_reads_whole(size):
    data = b'{\n  "a": [\n    1,\n    2\n  ]\n}\n{\n  "b": 3\n}\n'
    assert await _read(_sources(data, size=size)) == [({
        "a": [1, 2]
    }, "f0.json:6"), ({
        "b": 3
    }, "f0.json:9")]


@pytest.mark.asyncio
async def test_an_integer_past_64_bits_keeps_every_digit():
    assert await _values(b'{"n":100000000000000000001}\n') == [{
        "n":
        100000000000000000001
    }]


@pytest.mark.asyncio
async def test_jqs_own_numbers_and_the_json_around_them():
    values = await _values(b'[1]\nnan\n{"a":.5}\n')
    assert values[0] == [1] and math.isnan(values[1])
    assert values[2] == {"a": 0.5}


@pytest.mark.asyncio
async def test_a_parse_error_ends_the_stream_after_the_values_before_it():
    assert await _read(_sources(b"1\n2\n", b"[")) == [
        (1, "f0.json:1"), (2, "f0.json:2"),
        ("error", "Unfinished JSON term at EOF at line 3, column 1",
         "f1.json:0")
    ]
    assert await _read(_sources(b'{"a":1}\n1 [')) == [
        ({
            "a": 1
        }, "f0.json:1"), (1, "f0.json:1"),
        ("error", "Unfinished JSON term at EOF at line 2, column 3",
         "f0.json:1")
    ]


@pytest.mark.asyncio
async def test_a_bom_is_stripped_from_the_start_of_the_stream_only():
    assert await _values(b"\xef\xbb\xbf1\n") == [1]
    assert await _read(_sources(b"\xef\xbb\xbf1\n", b"\xef\xbb\xbf2\n")) == [
        (1, "f0.json:1"),
        ("error", "Invalid numeric literal at line 3, column 0", "f1.json:1")
    ]
    assert await _read(_sources(b"\xef\xbb1\n")) == [("error", "Malformed BOM",
                                                      "f0.json:1")]
    # The BOM check goes on from one input into the next, as jq's one
    # parser keeps it.
    assert await _read(_sources(b"\xef", b"1\n")
                       ) == [("error", "Malformed BOM", "f1.json:1")]


@pytest.mark.asyncio
async def test_slurp_is_one_value_for_every_input():
    opts = JqOptions(slurp=True)
    assert await _values(b'{"a":1}', b' {"b":2}', opts=opts) == [[{
        "a": 1
    }, {
        "b": 2
    }]]
    assert await _read(_sources(b"1\n", b"["), opts) == [
        ("error", "Unfinished JSON term at EOF at line 2, column 1",
         "f1.json:0")
    ]


@pytest.mark.asyncio
async def test_raw_lines_run_on_from_one_input_into_the_next():
    raw = JqOptions(raw_input=True)
    assert await _values(b"x\ny", b"z\n", opts=raw) == ["x", "yz"]
    assert await _values(b"a\nb", opts=raw) == ["a", "b"]
    assert await _values(b"", opts=raw) == []
    assert await _values(b"\n", opts=raw) == [""]
    assert await _values("a\N{LINE SEPARATOR}b\n".encode(),
                         opts=raw) == ["a\N{LINE SEPARATOR}b"]
    assert await _values(b"a\xffb\n\xf0\x80\x80\x80\n", opts=raw) == [
        "a\N{REPLACEMENT CHARACTER}b", "\N{REPLACEMENT CHARACTER}"
    ]


@pytest.mark.asyncio
async def test_raw_slurp_is_every_input_as_one_string():
    opts = JqOptions(raw_input=True, slurp=True)
    assert await _values(b"x\n", b"y", opts=opts) == ["x\ny"]


@pytest.mark.asyncio
async def test_seq_reports_a_parse_error_and_reads_on():
    opts = JqOptions(seq=True)
    assert await _read(_sources(b"\x1e1\n\x1e[1 2]\n\x1e3\n"), opts) == [
        (1, "f0.json:1"),
        ("error", "Expected separator between values at line 2, column 6 "
         "(need RS to resync)", "f0.json:2"), (3, "f0.json:3")
    ]
    assert await _read(_sources(b'{"a":1}\n'), opts) == [
        ("error", "Unfinished abandoned text at EOF at line 2, column 0",
         "f0.json:1")
    ]


@pytest.mark.asyncio
async def test_stream_hands_events_over_as_the_input_goes_by():
    opts = JqOptions(stream=True)
    assert await _read(_sources(b'[1,\n[2]]\n'),
                       opts) == [([[0], 1], "f0.json:1"),
                                 ([[1, 0], 2], "f0.json:2"),
                                 ([[1, 0]], "f0.json:2"), ([[1]], "f0.json:2")]
    assert await _read(_sources(b'{"a":[1,'), opts) == [
        ([["a", 0], 1], "f0.json:0"),
        ("error", "Unfinished JSON term at EOF at line 1, column 8",
         "f0.json:0")
    ]


@pytest.mark.asyncio
async def test_stream_and_slurp_collect_the_events():
    opts = JqOptions(stream=True, slurp=True)
    assert await _values(b"[1] [2]", opts=opts) == [[[[0], 1], [[0]], [[0], 2],
                                                     [[0]]]]


@pytest.mark.asyncio
async def test_no_input_at_all_reads_as_nothing():
    reader = InputReader([], JqOptions())
    assert await reader.next_input() is NO_VALUE
    assert reader.position() == "<unknown>"


@pytest.mark.asyncio
async def test_an_empty_input_holds_no_documents():
    assert await _values(b"") == []
    assert await _values(b"  \n\n ") == []


def test_pieces_end_at_a_newline_or_after_4091_bytes():
    data = b"ab\ncd\n"
    assert pieces_through(data, 0) == (3, 1)
    assert pieces_through(data, 4) == (6, 2)
    long = b"x" * (READ_CHUNK + 5) + b"\n"
    assert pieces_through(long, 10) == (READ_CHUNK, 0)
    assert pieces_through(long, READ_CHUNK + 1) == (len(long), 1)


def test_a_piece_ending_inside_a_character_reads_to_its_end():
    data = b"x" * (READ_CHUNK - 1) + "é".encode() + b"yz\n"
    assert pieces_through(data, 0) == (READ_CHUNK + 1, 0)


@pytest.mark.asyncio
async def test_read_values_reads_a_slurpfile_as_jq_does():
    source = InputSource("m.json", _chunks(b'{"a":1}\n{"a":2}\n', 4))
    assert await read_values(source) == ([{"a": 1}, {"a": 2}], None)
    values, failure = await read_values(
        InputSource("bad.json", _chunks(b"1 [", 99)))
    assert values == [1]
    assert failure == JqParseError(
        "Unfinished JSON term at EOF at line 1, column 3")


def test_parse_value_takes_one_value_as_jv_parse_does():
    assert parse_value(b'{"a":1}') == {"a": 1}
    assert math.isnan(parse_value(b"nan"))
    assert parse_value(b" 12 ") == 12
    assert parse_value(b"1 2") is NO_VALUE
    assert parse_value(b"") is NO_VALUE
    assert parse_value(b"nope") is NO_VALUE
    assert parse_value(b"[1,") is NO_VALUE


def test_is_jsonl_path():
    assert is_jsonl_path("/d/f.jsonl")
    assert is_jsonl_path("/d/f.ndjson")
    assert not is_jsonl_path("/d/f.json")
