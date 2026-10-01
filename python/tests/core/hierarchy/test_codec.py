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

from mirage.core.hierarchy.codec import (
    DATE,
    INT_JSON,
    JSON_NAME,
    JSONL_NAME,
    PATH_SAFE,
    RAW,
    ascii_digits,
)


def test_raw_takes_any_nonempty_segment():
    assert RAW.decode("anything") == "anything"
    assert RAW.decode("") is None


def test_json_name_strips_the_suffix_and_refuses_bare_ones():
    assert JSON_NAME.decode("trace1.json") == "trace1"
    assert JSON_NAME.decode("trace1.jsonl") is None
    assert JSON_NAME.decode(".json") is None
    assert JSON_NAME.decode("noext") is None
    assert JSON_NAME.encode("trace1") == "trace1.json"


def test_jsonl_name_is_the_jsonl_twin():
    assert JSONL_NAME.decode("run.jsonl") == "run"
    assert JSONL_NAME.decode("run.json") is None


def test_int_json_requires_plain_ascii_digits():
    assert INT_JSON.decode("12.json") == "12"
    assert INT_JSON.decode("007.json") == "007"
    # int() would accept these; parseInt would guess at the first; both
    # languages must refuse them identically.
    assert INT_JSON.decode("12abc.json") is None
    assert INT_JSON.decode("1.5.json") is None
    assert INT_JSON.decode("١٢.json") is None


def test_ascii_digits_guard():
    assert ascii_digits("42")
    assert not ascii_digits("4x2")
    assert not ascii_digits("")


def test_date_is_shape_only():
    # Shape only, not a calendar check: the dated-message backends mint
    # their date directories from real timestamps, so a shaped-but-absent
    # date resolves through the listing like any other name.
    assert DATE.decode("2024-01-15") == "2024-01-15"
    assert DATE.decode("2026-02-30") == "2026-02-30"
    assert DATE.decode("2024-1-15") is None
    assert DATE.decode("notadate") is None
    assert DATE.decode("2024-01-15x") is None


def test_path_safe_gives_every_value_its_own_segment():
    # ``/`` renders as ``∕``; a value already holding ``∕`` or ``⁄`` has that
    # character escaped, so ``a/b`` and ``a∕b`` cannot name one directory
    # and the decode recovers exactly the value that was rendered.
    assert PATH_SAFE.encode("a/b") == "a∕b"
    assert PATH_SAFE.encode("a∕b") == "a⁄∕b"
    assert PATH_SAFE.encode("a⁄b") == "a⁄⁄b"
    for raw in ("plain", "a/b", "a∕b", "a⁄b", "/∕⁄/", "⁄∕"):
        assert PATH_SAFE.decode(PATH_SAFE.encode(raw)) == raw
    assert len({PATH_SAFE.encode(raw) for raw in ("a/b", "a∕b", "a⁄∕b")}) == 3


def test_path_safe_keeps_blank_and_dot_led_values_addressable():
    # A blank value would render as ``unknown`` and a dot-led one as a
    # hidden segment, and neither could then be listed and opened as the
    # value it stands for. Both carry the escape lead instead: an empty
    # value is the lone lead, and the decode reads a lead with nothing
    # after it as escaping nothing.
    assert PATH_SAFE.encode("") == "⁄"
    assert PATH_SAFE.encode(" ") == "⁄ "
    assert PATH_SAFE.encode(".env") == "⁄.env"
    assert PATH_SAFE.encode("..") == "⁄.."
    assert PATH_SAFE.encode("unknown") == "unknown"
    edges = ("", " ", "  ", ".", "..", ".env", "./x", ".⁄", "⁄.x", "unknown")
    for raw in edges:
        assert PATH_SAFE.decode(PATH_SAFE.encode(raw)) == raw
        assert not PATH_SAFE.encode(raw).startswith(".")
    assert len({PATH_SAFE.encode(raw) for raw in edges}) == len(edges)
    assert PATH_SAFE.decode("⁄") == ""
    assert PATH_SAFE.decode("a⁄") == "a"
    assert PATH_SAFE.decode("") is None
    assert RAW.encode("a/b") == "a/b"


def test_path_safe_prefix_value_is_what_a_rendered_prefix_implies():
    # A backend that pushes a glob's literal head into a query needs the
    # VALUE prefix that rendered head stands for. A head cut inside an
    # escape pair drops the dangling lead, so the pushdown stays a sound
    # over-approximation the rendered-name filter then tightens.
    assert PATH_SAFE.prefix_value("doc-03") == "doc-03"
    assert PATH_SAFE.prefix_value("a∕") == "a/"
    assert PATH_SAFE.prefix_value("a⁄∕") == "a∕"
    assert PATH_SAFE.prefix_value("a⁄") == "a"
    assert PATH_SAFE.prefix_value("a⁄⁄") == "a⁄"
    assert PATH_SAFE.prefix_value("") == ""
    assert PATH_SAFE.prefix_value("⁄") == ""
    assert PATH_SAFE.prefix_value("⁄.e") == ".e"
    assert RAW.prefix_value("a∕") == "a∕"


def test_path_safe_blank_is_the_shared_white_space_set():
    # ``str.strip`` and JavaScript's ``trim`` disagree at the edges (U+001C
    # ..U+001F, U+0085, U+FEFF), so a value only one runtime called blank
    # took the lead in one tree and not the other. Blank is the White_Space
    # property in both, read from ``utils.sanitize``.
    assert PATH_SAFE.encode("\x85") == "⁄\x85"
    assert PATH_SAFE.encode("\u3000") == "⁄\u3000"
    assert PATH_SAFE.encode("\x1c") == "\x1c"
    assert PATH_SAFE.encode("\ufeff") == "\ufeff"
    for raw in ("\x85", "\u3000", "\x1c", "\ufeff"):
        assert PATH_SAFE.decode(PATH_SAFE.encode(raw)) == raw
