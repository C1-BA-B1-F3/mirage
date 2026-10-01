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

from mirage.commands.builtin.constants import PatternType
from mirage.commands.builtin.grep_pushdown import classify_pattern


def test_fixed_string_is_exact():
    assert classify_pattern("hello", fixed_string=True) == PatternType.EXACT


def test_fixed_string_with_metacharacters():
    assert classify_pattern("hello.*", fixed_string=True) == PatternType.EXACT


def test_simple_word():
    assert classify_pattern("hello", fixed_string=False) == PatternType.SIMPLE


def test_simple_phrase():
    result = classify_pattern("hello world", fixed_string=False)
    assert result == PatternType.SIMPLE


def test_simple_with_special_chars():
    result = classify_pattern("hello-world_v2.txt", fixed_string=False)
    assert result == PatternType.SIMPLE


def test_regex_dot_star():
    assert (
        classify_pattern("hello.*world", fixed_string=False)
        == PatternType.REGEX
    )


def test_regex_brackets():
    assert classify_pattern("[abc]+", fixed_string=False) == PatternType.REGEX


def test_regex_pipe():
    assert classify_pattern("foo|bar", fixed_string=False) == PatternType.REGEX


def test_regex_caret():
    assert classify_pattern("^start", fixed_string=False) == PatternType.REGEX


def test_regex_parens():
    assert classify_pattern("(group)", fixed_string=False) == PatternType.REGEX
