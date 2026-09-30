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

import pytest

from mirage.commands.builtin.utils.pcre import (PcreError, match_start,
                                                match_text, translate_pcre,
                                                user_groups)


def compiled(pattern: str,
             unicode: bool = False,
             ignore_case: bool = False) -> re.Pattern[str]:
    translated = translate_pcre(pattern, unicode, ignore_case)
    flags = re.IGNORECASE if translated.ignore_case else 0
    return re.compile(translated.source, flags | (0 if unicode else re.ASCII))


def only(pattern: str,
         text: str,
         unicode: bool = False,
         ignore_case: bool = False) -> list[str]:
    pat = compiled(pattern, unicode, ignore_case)
    return [t for t in (match_text(m) for m in pat.finditer(text)) if t]


# grep 3.11 -oP (PCRE2 10.46, no UCP) unless the row says unicode, which
# is ripgrep 14.1.1's -oP (PCRE2 10.43 with UTF and UCP).
@pytest.mark.parametrize("pattern,text,found,unicode", [
    (r"\d+", "abc 123 x45", ["123", "45"], False),
    (r"(?<=id=)\d+", "id=42 name=x", ["42"], False),
    (r"name=\K\w+", "id=42 name=x", ["x"], False),
    (r"\x{00a0}", "a\xa0b", ["\xa0"], False),
    (r"\t", "a\tb", ["\t"], False),
    (r"\h", "a b", [" "], False),
    (r"\Q.\E", "a.b", ["."], False),
    (r"\Q.b*", "a.b*c", [".b*"], False),
    (r"(a)\g{1}", "aa", ["aa"], False),
    (r"(a)\g1", "aa", ["aa"], False),
    (r"(a)\g{-1}", "aa", ["aa"], False),
    (r"(?<x>a)\k<x>", "aa", ["aa"], False),
    ("(?P<x>a)(?P=x)", "aa", ["aa"], False),
    (r"(?'x'a)\k'x'", "aa", ["aa"], False),
    (r"(?<x>a)\k{x}", "aa", ["aa"], False),
    ("(?>a+)a", "aaa", [], False),
    ("a++a", "aaa", [], False),
    ("a*+", "aaa", ["aaa"], False),
    ("a?+a", "aaa", ["aa"], False),
    ("(?i)a", "Aa", ["A", "a"], False),
    ("(?i:A)a", "Aa", ["Aa"], False),
    ("a(?i)b", "Ab", [], False),
    ("(?i)a(?-i)B", "AB", ["AB"], False),
    (r"\Aab\z", "ab", ["ab"], False),
    (r"\Aab\Z", "ab", ["ab"], False),
    (r"\w+", "aé", ["a"], False),
    (r"[[:alpha:]]+", "aé1", ["a"], False),
    (r"[\d]+", "ab12", ["12"], False),
    (r"[^\d]+", "ab12", ["ab"], False),
    (r"a\Kb|x", "ab", ["b"], False),
    (r"a\Ka", "aaa", ["a"], False),
    (r"foo=\K\d", "foo=1 foo=2", ["1", "2"], False),
    ("a(?#comment)b", "abc", ["ab"], False),
    ("(?x) a b # c", "abc", ["ab"], False),
    ("(?m)^a", "abc", ["a"], False),
    (r"\N", "aXb", ["a", "X", "b"], False),
    (r"\101", "A1", ["A"], False),
    ("[[:^alpha:]b]", "ab", ["b"], False),
    (r"\pL+", "ab", ["ab"], False),
    (r"\P{L}", "ab1", ["1"], False),
    (r"\p{L&}+", "ab", ["ab"], False),
    (r"\p{Xan}+", "ab1", ["ab1"], False),
    ("a{,2}", "aaa", ["aa", "a"], False),
    ("a{x}", "a{x}", ["a{x}"], False),
    ("a{,}", "a{,}", ["a{,}"], False),
    ("(?<=a|bc)x", "bcx ax", ["x", "x"], False),
    ("(a(?i)b|c)", "aC", ["C"], False),
    (r"(?x)a\ b", "a b", ["a b"], False),
    ("[[:<:]]a", "a", ["a"], False),
    ("(?i)a(?^)A", "aA", ["aA"], False),
    ("(*UTF)a", "a", ["a"], False),
    ("(?C1)a", "a", ["a"], False),
    ("(?=a)*a", "ab", ["a"], False),
    ("a{1,2}?", "aaa", ["a", "a", "a"], False),
    (r"\w+", "aé", ["aé"], True),
    (r"\d+", "a٣5", ["٣5"], True),
    (r"\s", "a\xa0b", ["\xa0"], True),
    (r"\s", "a᠎b", ["᠎"], True),
    (r"\w+", "a²b", ["a²b"], True),
    (r"\w+", "a‌b", ["a", "b"], True),
    ("[[:alpha:]]+", "aé", ["aé"], True),
    (r"\bé", "aé", [], True),
    (r"\x{e9}", "aé", ["é"], True),
])
def test_matches_as_pcre2(pattern, text, found, unicode):
    assert only(pattern, text, unicode) == found


def test_caseless_backreferences_fold_on_the_host():
    assert only(r"(a)\1", "aA", ignore_case=True) == ["aA"]
    assert only(r"(?i)(a)\1", "aA") == ["aA"]
    assert only(r"é", "Éé", unicode=True, ignore_case=True) == ["É", "é"]


def test_keep_moves_the_reported_start():
    pat = compiled(r"a\Kbc")
    m = pat.search("abc")
    assert m is not None
    assert (match_start(m), match_text(m)) == (1, "bc")


def test_keep_of_an_unmatched_branch_is_skipped():
    assert only(r"foo=\K\d|a\Ka", "foo=1 foo=2 aaa") == ["1", "2", "a"]


def test_user_groups_skip_the_markers():
    pat = compiled(r"a\K(b)(?<n>c)")
    assert user_groups(pat) == (2, 3)


# grep prints the message after `grep: `; ripgrep adds the offset. Each
# offset is ripgrep 14.1.1's for `(?:PATTERN)` less the three characters
# of its wrapper.
@pytest.mark.parametrize("pattern,message,offset", [
    ("(", "missing closing parenthesis", 1),
    ("(?:()", "missing closing parenthesis", 5),
    ("(?:a))", "unmatched closing parenthesis", 5),
    ("(?:[a)", "missing terminating ] for character class", 6),
    ("a\\", "\\ at end of pattern", 2),
    ("(?:*a)", "quantifier does not follow a repeatable item", 3),
    ("(?:a{2,1})", "numbers out of order in {} quantifier", 8),
    ("(?:(?<=a+)b)", "length of lookbehind assertion is not limited", 3),
    ("(?:(a)\\2)", "reference to non-existent subpattern", 7),
    ("(?:(?z))", "unrecognized character after (? or (?-", 5),
    ("(?:\\x{110000})", "character code point value in \\x{} or \\o{} is "
     "too large", 12),
    ("a**", "quantifier does not follow a repeatable item", 2),
    ("\\b*a", "quantifier does not follow a repeatable item", 2),
    ("a{2}{3}", "quantifier does not follow a repeatable item", 6),
    ("[\\d-z]", "invalid range in character class", 4),
    ("[z-a]", "range out of order in character class", 3),
    ("[[:foo:]]", "unknown POSIX class name", 8),
    ("\\x{zz}", "non-hex character in \\x{} (closing brace missing?)", 3),
    ("\\o{8}", "non-octal character in \\o{} (closing brace missing?)", 3),
    ("\\x", "digits missing after \\x or in \\x{} or \\o{} or \\N{U+}", 2),
    ("\\y", "unrecognized character follows \\", 1),
    ("\\p", "malformed \\P or \\p sequence", 2),
    ("[\\N]", "\\N is not supported in a class", 3),
    ("a{65536}", "number too big in {} quantifier", 7),
    ("(?<", "subpattern name expected", 3),
    ("(?<a", "syntax error in subpattern name (missing terminator?)", 4),
    ("(?<1a>x)", "subpattern name must start with a non-digit", 3),
    ("(?<a>x)(?<a>y)", "two named subpatterns have the same name "
     "(PCRE2_DUPNAMES not set)", 12),
    ("\\k<zz>", "reference to non-existent subpattern", 3),
    ("(?#x", "missing ) after (?# comment", 4),
    ("(?<=a\\Kb)c", "\\K is not allowed in lookarounds (but see "
     "PCRE2_EXTRA_ALLOW_LOOKAROUND_BSK)", 10),
    ("\\N{U+41}", "\\N{U+dddd} is supported only in Unicode (UTF) mode", 2),
    ("\\c", "\\c at end of pattern", 2),
    ("\\8", "reference to non-existent subpattern", 1),
    ("(?", "missing closing parenthesis", 2),
    ("\\ga", "\\g is not followed by a braced, angle-bracketed, or quoted "
     "name/number or by a plain number", 2),
])
def test_refusals_in_pcre2s_words(pattern, message, offset):
    with pytest.raises(PcreError) as caught:
        translate_pcre(pattern)
    assert (caught.value.message, caught.value.offset) == (message, offset)


@pytest.mark.parametrize("pattern", [
    r"\Gab", r"\X", "(ab)(?1)", "(?R)?a", r"(a)\g<1>", "(?|(a)|(b))",
    "(a)(?(1)b|c)", r"\p{Greek}", "(?<=a?b)c", "(?*a)", "(*SKIP)a",
    r"(a)(?i)\1"
])
def test_what_no_host_can_express_is_refused(pattern):
    with pytest.raises(PcreError) as caught:
        translate_pcre(pattern)
    assert caught.value.message.endswith("is not supported in mirage")
