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
import random

import jq as libjq
import pytest

from mirage.core.jq.parse import (JqParser, decode_utf8, number_value,
                                  utf8_missing)
from mirage.core.jq.types import NO_VALUE, JqParseError

# Every case below is jq 1.8.2's own output (debian:testing-slim):
# the values its parser yields, then the report of the error that stopped
# it, if one did.
NORMAL = [
    (b"1 [", [1], "Unfinished JSON term at EOF at line 1, column 3"),
    (b"truefalse", [], "Invalid literal at EOF at line 1, column 9"),
    (b"1true", [], "Invalid numeric literal at EOF at line 1, column 5"),
    (b"true x", [True], "Invalid numeric literal at EOF at line 1, column 6"),
    (b"1]", [], "Unmatched ']' at line 1, column 2"),
    (b"1 ]", [1], "Unmatched ']' at line 1, column 3"),
    (b"1 } 2", [1], "Unmatched '}' at line 1, column 3"),
    (b"[1]]", [[1]], "Unmatched ']' at line 1, column 4"),
    (b'{"a":1}}', [{
        "a": 1
    }], "Unmatched '}' at line 1, column 8"),
    (b"[1,]", [], "Expected another array element at line 1, column 4"),
    (b'{"a" 1}', [], "Expected separator between values at line 1, column 7"),
    (b'{"a":1 "b":2}', [],
     "Expected separator between values at line 1, column 10"),
    (b"[1 2]", [], "Expected separator between values at line 1, column 5"),
    (b"{1:2}", [], "Object keys must be strings at line 1, column 3"),
    (b"[1:2]", [], "':' not as part of an object at line 1, column 3"),
    (b'["a":1]', [], "':' not as part of an object at line 1, column 5"),
    (b'{"a":}', [], "Unmatched '}' at line 1, column 6"),
    (b"{,}", [], "Expected value before ',' at line 1, column 2"),
    (b"[,1]", [], "Expected value before ',' at line 1, column 2"),
    (b"1,2", [], "Expected value before ',' at line 1, column 2"),
    (b'{"a",1}', [],
     "Objects must consist of key:value pairs at line 1, column 5"),
    (b'{"a"}', [],
     "Objects must consist of key:value pairs at line 1, column 5"),
    (b"[1}", [],
     "Objects must consist of key:value pairs at line 1, column 3"),
    (b'{"a":1]', [], "Unmatched ']' at line 1, column 7"),
    (b'{"a":1,}', [], "Expected another key-value pair at line 1, column 8"),
    (b"]", [], "Unmatched ']' at line 1, column 1"),
    (b"}", [], "Unmatched '}' at line 1, column 1"),
    (b":", [], "Expected string key before ':' at line 1, column 1"),
    (b",", [], "Expected value before ',' at line 1, column 1"),
    (b'"a\x01b"', [], "Invalid string: control characters from U+0000 "
     "through U+001F must be escaped at line 1, column 5"),
    (b'"\x01"\n', [], "Invalid string: control characters from U+0000 "
     "through U+001F must be escaped at line 1, column 3"),
    (b'"a\x00b"', [], "Invalid string: control characters from U+0000 "
     "through U+001F must be escaped at line 1, column 5"),
    (b'"\\ud800"', [],
     "Invalid \\uXXXX\\uXXXX surrogate pair escape at line 1, column 8"),
    (b'"\\ud800\\u0041"', [],
     "Invalid \\uXXXX\\uXXXX surrogate pair escape at line 1, column 14"),
    (b'"\\ud800x"', [],
     "Invalid \\uXXXX\\uXXXX surrogate pair escape at line 1, column 9"),
    (b'"\\u12"', [], "Invalid \\uXXXX escape at line 1, column 6"),
    (b'"\\u12zz"', [],
     "Invalid characters in \\uXXXX escape at line 1, column 8"),
    (b'"\\x"', [], "Invalid escape at line 1, column 4"),
    (b'"abc', [], "Unfinished string at EOF at line 1, column 4"),
    (b'"a\\', [], "Unfinished string at EOF at line 1, column 3"),
    (b"'a'", [], "Invalid string literal; expected \", but got ' at EOF "
     "at line 1, column 3"),
    (b"nul", [], "Invalid literal at EOF at line 1, column 3"),
    (b"fals", [], "Invalid literal at EOF at line 1, column 4"),
    (b"nulll", [], "Invalid literal at EOF at line 1, column 5"),
    (b"truex", [], "Invalid literal at EOF at line 1, column 5"),
    (b"n", [], "Invalid numeric literal at EOF at line 1, column 1"),
    (b"nu", [], "Invalid literal at EOF at line 1, column 2"),
    (b"nan1 ", [], "Invalid numeric literal at line 1, column 5"),
    (b"sNaN1 ", [], "Invalid numeric literal at line 1, column 6"),
    (b"infinit ", [], "Invalid numeric literal at line 1, column 8"),
    (b"infinityx ", [], "Invalid numeric literal at line 1, column 10"),
    (b"1e ", [], "Invalid numeric literal at line 1, column 3"),
    (b"1e+ ", [], "Invalid numeric literal at line 1, column 4"),
    (b". ", [], "Invalid numeric literal at line 1, column 2"),
    (b"- ", [], "Invalid numeric literal at line 1, column 2"),
    (b"1.2.3 ", [], "Invalid numeric literal at line 1, column 6"),
    (b"0x10 ", [], "Invalid numeric literal at line 1, column 5"),
    (b"--1 ", [], "Invalid numeric literal at line 1, column 4"),
    (b"1\x002 ", [1], None),
    (b"\x00", [], "Invalid numeric literal at EOF at line 1, column 1"),
    (b"\xff", [], "Invalid numeric literal at EOF at line 1, column 1"),
    (b"[1,\x1e2", [], "Invalid numeric literal at EOF at line 1, column 5"),
    (b'{"a":1', [], "Unfinished JSON term at EOF at line 1, column 6"),
    (b'{"a"', [], "Unfinished JSON term at EOF at line 1, column 4"),
    (b'{"a":', [], "Unfinished JSON term at EOF at line 1, column 5"),
    (b"{", [], "Unfinished JSON term at EOF at line 1, column 1"),
    (b'{"a":1} {"a":', [{
        "a": 1
    }], "Unfinished JSON term at EOF at line 1, column 13"),
    (b"[1,2]\n\n\n{", [[1, 2]],
     "Unfinished JSON term at EOF at line 4, column 1"),
    (b"[" * 10001, [],
     "Exceeds depth limit for parsing at line 1, column 10001"),
    (b"[" * 10000, [], "Unfinished JSON term at EOF at line 1, column 10000"),
    (b"\xef\xbb\xbf1", [1], None),
    (b"\xef\xbb1", [], "Malformed BOM"),
    (b"\xef\xbb\xbf\xef\xbb\xbf1", [],
     "Invalid numeric literal at EOF at line 1, column 4"),
    (b"", [], None),
    (b"  \n\t ", [], None),
    (b"1.", [1.0], None),
    (b'{"b":1,"1":2}', [{
        "b": 1,
        "1": 2
    }], None),
]

STREAMING = [
    (b'[1,[2,3],{"a":4}]', [[[0], 1], [[1, 0], 2], [[1, 1], 3], [[1, 1]],
                            [[2, "a"], 4], [[2, "a"]], [[2]]], None),
    (b'{"a":[1,', [[["a", 0],
                    1]], "Unfinished JSON term at EOF at line 1, column 8"),
    (b"[1,2", [[[0], 1]], "Unfinished JSON term at EOF at line 1, column 4"),
    (b'1 2 "x" [] {}', [[[], 1], [[], 2], [[], "x"], [[], []], [[],
                                                                {}]], None),
    (b'{"a" 1}', [], "Expected separator between values at line 1, column 7"),
    (b"[1 2]", [], "Expected separator between values at line 1, column 5"),
    (b"]", [], "Unmatched ']' at the top-level at line 1, column 1"),
    (b"{]", [],
     "Unmatched ']' in the middle of an object at line 1, column 2"),
    (b"[1}", [],
     "Unmatched '}' in the middle of an array at line 1, column 3"),
    (b'{"a":1]', [],
     "Unmatched ']' in the middle of an object at line 1, column 7"),
    (b'{"a":}', [], "Missing value in key:value pair at line 1, column 6"),
    (b"{,}", [], "Expected value before ',' at line 1, column 2"),
    (b"[1,]", [[[0],
                1]], "Expected another array element at line 1, column 4"),
    (b'{"a":1,}', [[["a"], 1]],
     "Expected another key:value pair at line 1, column 8"),
    (b'{["a"]}', [], "Expected string key after '{', not '[' at line 1, "
     "column 2"),
    (b'{"a":1,["b"]}', [[["a"], 1]],
     "Expected string key after ',' in object, not '[' at line 1, column 8"),
    (b"{{}}", [], "Expected string key after '{', not '{' at line 1, "
     "column 2"),
    (b'{"a":1,{}}', [[["a"], 1]],
     "Expected string key after ',' in object, not '{' at line 1, column 8"),
    (b"1 : 2", [[[], 1]], "':' not as part of an object at line 1, column 3"),
    (b"[1:2]", [], "':' not as part of an object at line 1, column 3"),
    (b"{1:2}", [], "Object keys must be strings at line 1, column 3"),
    (b'{"a" "b"}', [],
     "Expected separator between values at line 1, column 8"),
    (b",", [], "Expected value before ',' at line 1, column 1"),
    (b'{"a":1 "b":2}', [],
     "Expected separator between values at line 1, column 10"),
    (b"[[1]", [[[0, 0], 1],
               [[0, 0]]], "Unfinished JSON term at EOF at line 1, column 4"),
    (b"[1] 2 x", [[[0], 1], [[0]],
                  [[],
                   2]], "Invalid numeric literal at EOF at line 1, column 7"),
]

# --seq reports a parse error and reads on, so its errors sit among the
# values in the order the parser met them.
SEQ = [
    (b"\x1e1\n\x1e[2]\n", [1, [2]]),
    (b"\x1e1\n\x1e[2", [1, "Unfinished JSON term at EOF at line 2, column 3"]),
    (b'\x1e{"a":1}\x1e{"b":2}\n', [{
        "a": 1
    }, {
        "b": 2
    }]),
    (b"\x1e[1,\x1e2\n", ["Truncated value at line 1, column 5", 2]),
    (b"\x1e[1 2]\n\x1e3\n", [
        "Expected separator between values at line 1, column 6 "
        "(need RS to resync)", 3
    ]),
    (b'\x1e"abc\n', ["Unfinished string at EOF at line 2, column 0"]),
    (b"\x1etrue\x1e", ["Truncated value at line 1, column 6"]),
    (b'\x1e"a"', ["a"]),
    (b"\x1e1 \x1e2 ", [1, 2]),
    (b"1 2", ["Unfinished abandoned text at EOF at line 1, column 3"]),
    (b"1 2 [", ["Unfinished abandoned text at EOF at line 1, column 5"]),
    (b"\x1e\x1e1\n", [1]),
    (b"x\x1e1\n", [1]),
    (b"[\x1e1\n", [1]),
    (b"\x1e1\x1e",
     ["Potentially truncated top-level numeric value at line 1, column 3"]),
    (b'\x1e{"a":1}', [{
        "a": 1
    }]),
    (b"\xef\xbb", ["Unfinished abandoned text at EOF at line 1, column 0"]),
    (b"\x1e1\x1e[\x1e2", [
        "Potentially truncated top-level numeric value at line 1, column 3",
        "Truncated value at line 1, column 5",
        "Potentially truncated top-level numeric value at EOF at line 1, "
        "column 6"
    ]),
]

SEQ_STREAMING = [
    (b"\x1e1\n", [[[], 1]]),
    (b"\x1e[1,2]\n", [[[0], 1], [[1], 2], [[1]]]),
    (b"\x1e[1,2\x1e3\n", [[[0], 1], "Truncated value at line 1, column 6",
                          [[], 3]]),
]


def _same(a: object, b: object) -> bool:
    if isinstance(a, float) and isinstance(
            b, float) and math.isnan(a) and math.isnan(b):
        return True
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return list(a) == list(b) and all(_same(a[k], b[k]) for k in a)
    return type(a) is type(b) and a == b


def _drain(parser: JqParser, seq: bool) -> list:
    # An RS under --seq can end a call with nothing to hand back while
    # the buffer still holds bytes, so pull until the buffer is used up.
    out: list = []
    while True:
        value = parser.next()
        if value is NO_VALUE:
            if parser.remaining():
                continue
            return out
        if isinstance(value, JqParseError):
            out.append(value)
            if not seq:
                return out
            continue
        out.append(value)


def _whole(data: bytes, seq: bool = False, streaming: bool = False) -> list:
    parser = JqParser(seq=seq, streaming=streaming)
    parser.feed(data, False)
    return _drain(parser, seq)


def _bytewise(data: bytes, seq: bool = False, streaming: bool = False) -> list:
    parser = JqParser(seq=seq, streaming=streaming)
    out: list = []
    for i in range(len(data)):
        parser.feed(data[i:i + 1], True)
        got = _drain(parser, seq)
        out.extend(got)
        if got and isinstance(got[-1], JqParseError) and not seq:
            return out
    parser.feed(b"", False)
    return out + _drain(parser, seq)


def _split(got: list) -> tuple[list, str | None]:
    if got and isinstance(got[-1], JqParseError):
        return got[:-1], got[-1].message
    return got, None


def _flat(got: list) -> list:
    return [g.message if isinstance(g, JqParseError) else g for g in got]


@pytest.mark.parametrize("data,values,error", NORMAL)
def test_normal_mode_matches_jq(data, values, error):
    for read in (_whole, _bytewise):
        got, message = _split(read(data))
        assert _same(got, values)
        assert message == error


@pytest.mark.parametrize("data,values,error", STREAMING)
def test_stream_mode_matches_jq(data, values, error):
    for read in (_whole, _bytewise):
        got, message = _split(read(data, streaming=True))
        assert _same(got, values)
        assert message == error


def test_stream_mode_holds_to_the_ordinary_parsers_depth_limit():
    # jq's streaming parser has no depth limit; mirage's has the ordinary
    # parser's, counted in containers.
    too_deep = "Exceeds depth limit for parsing at line 1, column {}"
    assert _flat(_whole(b"[" * 10001,
                        streaming=True)) == [too_deep.format(10001)]
    assert _flat(_whole(b'{"a":' * 10001,
                        streaming=True)) == [too_deep.format(50001)]
    events = _whole(b"[" * 10000 + b"]" * 10000, streaming=True)
    assert len(events) == 10000
    assert events[0] == [[0] * 9999, []] and events[-1] == [[0]]


@pytest.mark.parametrize("data,expected", SEQ)
def test_seq_mode_reports_and_reads_on(data, expected):
    for read in (_whole, _bytewise):
        assert _same(_flat(read(data, seq=True)), expected)


@pytest.mark.parametrize("data,expected", SEQ_STREAMING)
def test_seq_stream_mode_matches_jq(data, expected):
    for read in (_whole, _bytewise):
        assert _same(_flat(read(data, seq=True, streaming=True)), expected)


def test_numbers_take_what_decnumber_reads():
    got = _whole(b"nan NaN Infinity -Infinity +1 .5 1. 01 -0 1.000 1e2 "
                 b"100000000000000000001 -nan snan inf INF iNfInItY nan0 ")
    assert all(math.isnan(value) for value in got[:2])
    assert got[2:12] == [
        math.inf, -math.inf, 1, 0.5, 1.0, 1, 0, 1.0, 100.0,
        100000000000000000001
    ]
    assert all(math.isnan(value) for value in got[12:14])
    assert got[14:17] == [math.inf, math.inf, math.inf]
    assert math.isnan(got[17])


@pytest.mark.parametrize("literal,value", [
    (b"12", 12),
    (b"+1", 1),
    (b"007", 7),
    (b"-0", 0),
    (b".5", 0.5),
    (b"1.", 1.0),
    (b"1.e5", 100000.0),
    (b"-infinity", -math.inf),
    (b"x", NO_VALUE),
    (b"1e", NO_VALUE),
    (b"nan1", NO_VALUE),
    (b"", NO_VALUE),
])
def test_number_value(literal, value):
    assert number_value(literal) == value


def test_an_integer_past_the_digits_cpython_converts_reads_as_a_double():
    assert number_value(b"1" * 5000) == math.inf


@pytest.mark.parametrize("data,text", [
    (b"plain", "plain"),
    (b"\xf0\x80\x80\x80", "\N{REPLACEMENT CHARACTER}"),
    (b"\xed\xa0\x80", "\N{REPLACEMENT CHARACTER}"),
    (b"\xf4\x90\x80\x80", "\N{REPLACEMENT CHARACTER}"),
    (b"\xe2\x82", "\N{REPLACEMENT CHARACTER}"),
    (b"\xc0\x80", "\N{REPLACEMENT CHARACTER}\N{REPLACEMENT CHARACTER}"),
    (b"\xe2\x82x", "\N{REPLACEMENT CHARACTER}x"),
    (b"\xe2a", "\N{REPLACEMENT CHARACTER}"),
    (b"a\xffb", "a\N{REPLACEMENT CHARACTER}b"),
])
def test_decode_utf8_replaces_each_bad_sequence_once(data, text):
    assert decode_utf8(data) == text


def test_strings_decode_with_jqs_replacement():
    assert _whole(b'"\xf0\x80\x80\x80" "\xe2a" "\\udc00"') == [
        "\N{REPLACEMENT CHARACTER}", "\N{REPLACEMENT CHARACTER}",
        "\N{REPLACEMENT CHARACTER}"
    ]


@pytest.mark.parametrize("piece,missing", [
    (b"a", 0),
    (b"ab", 0),
    (b"a\xe2", 2),
    (b"a\xe2\x82", 1),
    (b"a\xe2\x82\xac", 0),
    (b"a\xf0\x9f", 2),
    (b"a\x80", 0),
    (b"a\xff", 0),
])
def test_utf8_missing(piece, missing):
    assert utf8_missing(piece) == missing


def test_a_proto_key_is_an_ordinary_key():
    assert _whole(b'{"__proto__":1,"a":[]}') == [{"__proto__": 1, "a": []}]


def test_a_duplicate_key_keeps_its_place_and_the_last_value():
    assert list(_whole(b'{"a":1,"b":2,"a":3}')[0].items()) == [("a", 3),
                                                               ("b", 2)]


ALPHABET = [
    "{", "}", "[", "]", ":", ",", '"', "\\", " ", "\n", "\t", "1", "0", "-",
    "+", ".", "e", "E", "t", "r", "u", "n", "a", "f", "l", "s", "x", "\x01",
    "\x00", "é", '"a"', "true", "null", "false", "12", '"\\u00e9"',
    '"\\ud83d\\ude00"', '"\\ud800"', '"\\udc00"', "\\u", "nan", "NaN", "inf",
    "1e5", ".5", '"\\n"', '{"k":1}', "[1,2]", "'",
    "\N{ZERO WIDTH NO-BREAK SPACE}"
]
SEEDS = [
    '{"a":1,"b":[1,2,{"c":null}]}', "[1,2,3]", '"str"', "123", "true",
    '{"a":{"b":{"c":[true,false]}}}', '[{"x":"y"},{"z":[]}]', "1 2 3",
    '{"a":1}\n{"b":2}\n', "[]", "{}", "[[[]]]", "-0.5e10", '"a\\"b"'
]


def _mutant(rng: random.Random) -> str:
    if rng.random() < 0.5:
        return "".join(rng.choice(ALPHABET) for _ in range(rng.randint(0, 12)))
    text = list(rng.choice(SEEDS))
    for _ in range(rng.randint(0, 3)):
        at = rng.randint(0, len(text))
        roll = rng.random()
        if roll < 0.33 and text:
            del text[min(at, len(text) - 1)]
        elif roll < 0.66:
            text.insert(at, rng.choice(ALPHABET))
        elif text:
            text[min(at, len(text) - 1)] = rng.choice(ALPHABET)
    return "".join(text)


def _libjq(text: str) -> tuple[list, str | None]:
    values: list = []
    try:
        for value in libjq.compile(".").input_text(text):
            values.append(value)
    except ValueError as exc:
        return values, str(exc).removeprefix("parse error: ")
    return values, None


def _loose(a: object, b: object) -> bool:
    # jq.py hands NaN back as None and a whole float back as an int.
    if isinstance(b, float) and math.isnan(b):
        return a is None or (isinstance(a, float) and math.isnan(a))
    if isinstance(a, (int, float)) and isinstance(
            b, (int, float)) and (not isinstance(a, bool)
                                  and not isinstance(b, bool)):
        if math.isinf(b):
            return abs(a) >= 1.7976931348623157e308 and (a > 0) == (b > 0)
        return float(a) == float(b)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_loose(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return list(a) == list(b) and all(_loose(a[k], b[k]) for k in a)
    return type(a) is type(b) and a == b


def test_parser_agrees_with_libjq_on_generated_input():
    rng = random.Random(1325)
    for _ in range(3000):
        text = _mutant(rng)
        values, message = _libjq(text)
        for read in (_whole, _bytewise):
            got, got_message = _split(read(text.encode()))
            assert got_message == message, text
            assert _loose(values, got), text
