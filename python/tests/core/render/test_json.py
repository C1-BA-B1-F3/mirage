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

from mirage.core.render.json import (compact_json_bytes, compact_json_text,
                                     json_bytes, json_text, jsonl_bytes,
                                     number_text, value_text)

# Byte-for-byte the fixture in the typescript twin
# (packages/core/src/core/render/json.test.ts). Both languages pin the same
# expected strings, so a change to either renderer breaks one of the two.
PAYLOAD = {
    "name": "café 中文",
    "tags": ["a", "b"],
    "meta": {
        "n": 1,
        "ok": True,
        "none": None
    },
    "empty": {},
}

INDENTED = ('{\n'
            '  "name": "café 中文",\n'
            '  "tags": [\n'
            '    "a",\n'
            '    "b"\n'
            '  ],\n'
            '  "meta": {\n'
            '    "n": 1,\n'
            '    "ok": true,\n'
            '    "none": null\n'
            '  },\n'
            '  "empty": {}\n'
            '}')

COMPACT = ('{"name":"café 中文","tags":["a","b"],'
           '"meta":{"n":1,"ok":true,"none":null},"empty":{}}')


def test_json_text_indents_two_and_keeps_non_ascii():
    assert json_text(PAYLOAD) == INDENTED


def test_json_bytes_indents_two_and_keeps_non_ascii():
    assert json_bytes(PAYLOAD) == INDENTED.encode()


def test_compact_json_text_has_no_separator_padding():
    assert compact_json_text(PAYLOAD) == COMPACT


def test_compact_json_bytes_encodes_the_text():
    assert compact_json_bytes(PAYLOAD) == COMPACT.encode()


def test_jsonl_bytes_terminates_every_row():
    assert jsonl_bytes([{"a": 1}, {"b": 2}]) == b'{"a":1}\n{"b":2}\n'


def test_jsonl_bytes_renders_no_rows_as_empty():
    assert jsonl_bytes([]) == b""


def test_jsonl_bytes_keeps_the_given_order():
    rows = [{"i": 2}, {"i": 1}]
    assert jsonl_bytes(rows) == b'{"i":2}\n{"i":1}\n'


def test_value_text_spells_a_value_as_its_json_does():
    # A string is itself; anything else is its compact JSON, so a boolean
    # is ``true`` in both languages rather than Python's ``True``, and an
    # integral float is the integer TypeScript never told it apart from.
    assert value_text("x") == "x"
    assert value_text("True") == "True"
    assert value_text(True) == "true"
    assert value_text(False) == "false"
    assert value_text(7) == "7"
    assert value_text(1.0) == "1"
    assert value_text(1.5) == "1.5"
    assert value_text(None) == "null"
    assert value_text({
        "a": 1.0,
        "b": [True, None]
    }) == '{"a":1,"b":[true,null]}'


def test_number_text_lays_a_float_out_as_ecmascript_does():
    # Python's repr and V8 agree on the digits and differ only on layout:
    # Python pads the exponent and switches to it below 1e-4 and from 1e16,
    # ECMAScript switches below 1e-6 and from 1e21. The same table as the
    # typescript twin, where String() is the spec this reproduces.
    assert number_text(1e-7) == "1e-7"
    assert number_text(0.00001) == "0.00001"
    assert number_text(1.5e-5) == "0.000015"
    assert number_text(1e16) == "10000000000000000"
    assert number_text(1e21) == "1e+21"
    assert number_text(1.5e22) == "1.5e+22"
    assert number_text(123.0) == "123"
    assert number_text(-0.0) == "0"
    assert number_text(-1e-7) == "-1e-7"
    assert number_text(0.30000000000000004) == "0.30000000000000004"
    assert number_text(float("nan")) == "null"
    assert number_text(float("inf")) == "null"


def test_value_text_spells_a_float_the_way_typescript_does():
    # A label holding 1e-7 used to spell 1e-07 here and 1e-7 there, so one
    # point had two paths; a nested number spells the same way.
    assert value_text(1e-7) == "1e-7"
    assert value_text(1e21) == "1e+21"
    assert value_text({"a": 1e-7, "b": [1e21]}) == '{"a":1e-7,"b":[1e+21]}'


def test_jsonl_numbers_match_ecmascript_inside_nested_cells():
    rows = [{
        "cells": [1e-5, 1e-7, 1e20, 1e21, 1.0, -0.0, {
            "number": -1.5e-5
        }]
    }]
    assert jsonl_bytes(rows) == (
        b'{"cells":[0.00001,1e-7,100000000000000000000,1e+21,1,0,'
        b'{"number":-0.000015}]}\n')
