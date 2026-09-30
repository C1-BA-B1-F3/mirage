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

import re

from mirage.commands.builtin.utils.charset import (ALL, MAX_CODE_POINT,
                                                   CharSet, host_char,
                                                   host_class)


def test_of_merges_overlapping_and_adjacent_ranges():
    assert CharSet.of((5, 9), (1, 3), (4, 4),
                      (20, 22)).ranges == ((1, 9), (20, 22))


def test_set_algebra():
    a = CharSet.of((ord("a"), ord("z")))
    b = CharSet.of((ord("m"), ord("p")))
    assert a.intersect(b) == b
    assert a.minus(b).ranges == ((ord("a"), ord("l")), (ord("q"), ord("z")))
    assert a.xor(CharSet.of(
        (ord("x"), ord("~")))).ranges == ((ord("a"), ord("w")), (ord("{"),
                                                                 ord("~")))
    assert b.union(a) == a


def test_negation_is_over_scalar_values():
    negated = CharSet.chars(ord("a")).negate()
    assert not negated.contains(ord("a"))
    assert not negated.contains(0xD800)
    assert negated.contains(MAX_CODE_POINT)
    assert negated.negate() == CharSet.chars(ord("a"))
    assert not ALL.contains(0xDFFF)


def test_single_and_empty():
    assert CharSet.chars(7).single() == 7
    assert CharSet.of((1, 2)).single() is None
    assert CharSet().is_empty()


def test_host_char_keeps_printable_ascii_readable():
    assert host_char(ord("a")) == "a"
    assert host_char(ord(".")) == "\\."
    assert host_char(ord("-")) == "-"
    assert re.fullmatch(host_char(0xA0), "\xa0")
    assert re.fullmatch(host_char(0x1F600), chr(0x1F600))


def test_host_class_matches_exactly_its_members():
    for cs in (CharSet.chars(ord("]"), ord("^"),
                             ord("-")), CharSet.of(
                                 (0x20, 0x7E)).negate(), CharSet()):
        pattern = re.compile(host_class(cs))
        for cp in (0x20, ord("]"), ord("^"), ord("-"), 0xA0, 0x1F600, 0xDC80):
            assert bool(pattern.fullmatch(chr(cp))) is cs.contains(cp)
