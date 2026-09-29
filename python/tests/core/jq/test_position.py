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

from mirage.core.jq.position import InputPositions, lines_read, value_end


@pytest.mark.parametrize("text, stop, expected", [
    ('"a" 1', 3, 2),
    ("[1] ", 3, 2),
    ("{} ", 2, 1),
    ("12 3", 2, 2),
    ("true", 4, 4),
])
def test_a_value_is_whole_at_its_closer_or_the_character_after(
        text, stop, expected):
    assert value_end(text, stop) == expected


def test_lines_count_the_newlines_read_through_each_line():
    text = "1 2\n3\n4"
    assert lines_read(text, [1, 3, 5, len(text)]) == [1, 1, 2, 2]


def _counts(text: str, numbers: int) -> list[int]:
    # Every "1 " value on the first line, placed at the space after it.
    first = text.index("1 ")
    return lines_read(text, [first + 2 * k + 1 for k in range(numbers)])


def test_a_long_line_counts_once_the_reader_holds_its_last_piece():
    # jq 1.8.2 reads a long line 4091 bytes at a time: of 4095 values on
    # one 8190-byte line, only the last four arrive with its newline.
    counts = _counts("1 " * 4095 + "\n2\n", 4095)
    assert (counts.count(0), counts.count(1)) == (4091, 4)


def test_a_piece_reads_on_to_the_end_of_a_character():
    # The first piece ends inside an é, reads one more byte to finish it,
    # and so every later piece starts a byte on (pinned: 2044 and 56).
    text = '"a' + "é" * 2045 + '"  ' + "1 " * 2100 + "\n"
    counts = _counts(text, 2100)
    assert (counts.count(0), counts.count(1)) == (2044, 56)


def test_positions_name_each_input_and_its_lines():
    positions = InputPositions(["<stdin>", "b.json"], ["1\n2\n", "3"],
                               [(0, 1), (0, 3), (1, 1)])
    assert [positions.at(doc)
            for doc in range(3)] == ["<stdin>:1", "<stdin>:2", "b.json:0"]
    assert positions.end() == "b.json:0"


def test_a_document_with_no_input_stands_at_the_end():
    positions = InputPositions([], [], [])
    assert positions.at(0) == "<stdin>:0"
    assert positions.end() == "<stdin>:0"
