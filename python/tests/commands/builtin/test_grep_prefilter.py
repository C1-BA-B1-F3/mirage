import re
from itertools import product

import pytest

from mirage.commands.builtin.grep_prefilter import required_needles


@pytest.mark.parametrize("source,expected", [
    ("zzqqxx", (b"zzqqxx", )),
    ("zzqqxx|qqzzyy", (b"zzqqxx", b"qqzzyy")),
    ("(?:zzqqxx)|(?:qqzzyy)", (b"zzqqxx", b"qqzzyy")),
    ("zz.qxx", (b"qxx", )),
    (r"\bfoo\b", (b"foo", )),
    ("foo[0-9]+", (b"foo", )),
    ("a?bc", (b"bc", )),
    ("a{0,3}bc", (b"bc", )),
    ("foo(?:bar)?", (b"foo", )),
    ("foo|", None),
    ("(?:foo)?", None),
    (r"\d+", None),
    ("(?i:foo)", None),
    (r"(foo)\1", None),
    (r"\x66oo", None),
    ("é", None),
])
def test_conservative_requirements(source, expected):
    assert required_needles(re.compile(source)) == expected


def test_never_reject_matching_lines_across_regex_operators():
    atoms = [
        "a", "bc", "[ab]", ".", r"\b", "(?:a|bc)", "(a|)", "a?b", "a{0,2}"
    ]
    texts = [
        "", "a", "b", "c", "ab", "abc", "bc", "ac", "bb", "aabc", "bcc",
        "abcabc"
    ]
    for left, right, join, suffix in product(
            atoms, atoms, ["", "|"], ["", "?", "*", "+", "{0,2}", "{2}"]):
        pat = re.compile(f"(?:{left}{join}{right}){suffix}")
        needles = required_needles(pat)
        if needles is None:
            continue
        for text in texts:
            if pat.search(text):
                assert any(n in text.encode() for n in needles), (pat, text)
