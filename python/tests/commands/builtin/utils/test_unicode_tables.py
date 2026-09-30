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

from mirage.commands.builtin.utils.charset import CharSet
from mirage.commands.builtin.utils.unicode_tables import (canonical_category,
                                                          category, fold,
                                                          fold_orbits,
                                                          pcre_word, rust_word,
                                                          unicode_property)


@pytest.mark.parametrize("name,short", [
    ("L", "L"),
    ("Lu", "Lu"),
    ("letter", "L"),
    ("Decimal_Number", "Nd"),
    ("decimal number", "Nd"),
    ("gc=Nd", "Nd"),
    ("General_Category=Lu", "Lu"),
    ("Greek", None),
])
def test_canonical_category(name, short):
    assert canonical_category(name) == short


def test_categories_hold_what_the_name_says():
    assert category("Nd").contains(ord("٣"))
    assert category("Lu").contains(ord("É"))
    assert not category("Lu").contains(ord("é"))
    assert category("L").contains(ord("é"))


def test_properties_both_dialects_spell_alike():
    assert unicode_property("Any").contains(0x10FFFF)
    assert unicode_property("ASCII") == CharSet.of((0, 0x7F))
    assert not unicode_property("Assigned").contains(0x0378)
    assert unicode_property("Greek") is None


# Measured with ripgrep 14.1.1 and PCRE2 10.43 (`rg -o '\w+'` and
# `rg -oP '\w+'`): the two engines disagree about ², ZWNJ and Ⓐ.
@pytest.mark.parametrize("ch,rust,pcre", [
    ("é", True, True),
    ("١", True, True),
    (chr(0x301), True, True),
    ("‿", True, True),
    ("²", False, True),
    ("Ⅰ", True, True),
    ("Ⓐ", True, False),
    (chr(0x200C), True, False),
    (" ", False, False),
])
def test_word_classes(ch, rust, pcre):
    assert rust_word().contains(ord(ch)) is rust
    assert pcre_word().contains(ord(ch)) is pcre


def test_simple_case_folding():
    orbits = fold_orbits()
    assert orbits[ord("k")] == (ord("K"), ord("k"), 0x212A)
    assert orbits[ord("s")] == (ord("S"), ord("s"), 0x17F)
    assert ord("ı") not in orbits
    assert orbits[ord("ß")] == (ord("ß"), 0x1E9E)
    assert fold(CharSet.chars(ord("k")),
                True) == CharSet.chars(ord("K"), ord("k"))
    assert fold(CharSet.of((ord("a"), ord("c"))), False).contains(ord("B"))
