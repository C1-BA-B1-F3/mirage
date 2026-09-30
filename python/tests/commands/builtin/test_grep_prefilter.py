import re
from itertools import product

import pytest

from mirage.commands.builtin.grep_prefilter import LONGEST, required_needles


@pytest.mark.parametrize("source,expected", [
    ("zzqqxx", (b"zzqqxx", )),
    ("zzqqxx|qqzzyy", (b"zzqqxx", b"qqzzyy")),
    ("(?:zzqqxx)|(?:qqzzyy)", (b"zzqqxx", b"qqzzyy")),
    ("^(zzqqxx|qqzzyy)$", (b"zzqqxx", b"qqzzyy")),
    ("zz.qxx", (b"qxx", )),
    (r"\bfoo\b", (b"foo", )),
    (r"(?<!\w)(?:needle)(?!\w)", (b"needle", )),
    ("a(?=b)c", (b"ac", )),
    ("foo[0-9]+", (b"foo", )),
    ("a?bc", (b"bc", )),
    ("x*required", (b"required", )),
    ("a{0,3}bc", (b"bc", )),
    ("a{2,3}b", (b"a", )),
    (r"a\+b", (b"a+b", )),
    ("[a-z]+required", (b"required", )),
    ("(?:foo|bar)+required", (b"required", )),
    ("foo(?:bar)?", (b"foo", )),
    ("(?P<name>foo)bar", (b"foobar", )),
    ("(?>foo)bar", (b"foobar", )),
    (r"foo\tbar", (b"foo", )),
    ("(?:ab|ab)c", (b"abc", )),
])
def test_conservative_requirements(source, expected):
    assert required_needles(re.compile(source)) == expected


@pytest.mark.parametrize("source", [
    "foo|",
    "(?:foo)?",
    "a*",
    "a?|b",
    "a{0,2}",
    "(?:)",
    r"\d+",
    "(?i:foo)",
    "(?#foo)",
    r"(foo)\1",
    "(?P<name>a)(?P=name)",
    r"\x66oo",
    "a{,3}b",
    "a{b",
    "a++b",
    "[]a]foo",
    "[^]a]foo",
    "[x[]foo",
    "é",
    "(" * 100 + "a" + ")" * 100,
    "|".join(f"word{i}" for i in range(100)),
])
def test_falls_back_on_nullable_or_unknown_syntax(source):
    assert required_needles(re.compile(source)) is None


def test_folds_ascii_and_declines_unicode_folding():
    assert required_needles(re.compile("Foo|FOO|bar",
                                       re.ASCII | re.I)) == (b"foo", b"bar")
    assert required_needles(re.compile("s", re.I)) is None
    assert required_needles(re.compile("a b", re.VERBOSE)) is None


def test_unicode_folding_keeps_needles_no_non_ascii_letter_folds_to():
    # Only `ı`, `İ`, the Kelvin sign and `ſ` fold onto ASCII letters
    # under python's Unicode IGNORECASE, so `needle` still narrows.
    assert required_needles(re.compile("Needle", re.I)) == (b"needle", )
    assert required_needles(re.compile("kin", re.I)) is None


def test_reads_anchors_as_consuming_nothing():
    assert required_needles(re.compile(r"\Afoo\Z")) == (b"foo", )


def test_bounds_the_source_and_builds_long_literals_once():
    assert required_needles(re.compile("a" * LONGEST)) == (b"a" * LONGEST, )
    assert required_needles(re.compile("a" * (LONGEST + 1))) is None


def admits(needles, line, flags):
    data = line.encode()
    if flags & re.IGNORECASE:
        data = data.lower()
    return needles is None or any(needle in data for needle in needles)


@pytest.mark.parametrize("flags", [0, re.I, re.ASCII, re.ASCII | re.I])
def test_never_rejects_a_matching_line(flags):
    atoms = [
        "a", "bc", "A", "[ab]", ".", r"\w", r"\b", r"\.", "(a|bc)", "(?:a|)",
        "a?", "a*", "a+", "a{0,2}", "a{2}", "a+?", "^a", "c$", r"\ba\b",
        "(?=b)", "(?!a)", "(?<=a)", "(?<!b)", "(?P<n>a)", "a?b"
    ]
    lines = [
        "", "a", "A", "b", "c", "ab", "bc", "Bc", "aa", "ac", "bb", "abc",
        "abbc", "aabc", "bcc", "abcabc", " bca ", "a.b", "éa", "K", "k", "K",
        "ſ", "S", "BC"
    ]
    for left, right in product(atoms, repeat=2):
        if left == right == "(?P<n>a)":
            continue
        sources = [left + right, f"(?:{left}|{right})"]
        sources += [
            f"(?:{left}{right}){suffix}"
            for suffix in ["?", "*", "+", "{0,2}", "{2}"]
        ]
        for source in sources:
            pat = re.compile(source, flags)
            needles = required_needles(pat)
            for line in lines:
                if pat.search(line):
                    assert admits(needles, line, flags), (pat, line)
