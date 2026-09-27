import re
from collections.abc import AsyncIterator
from itertools import product

import pytest

from mirage.commands.builtin.generic.grep import parse_flags as grep_flags
from mirage.commands.builtin.generic.rg import parse_flags as rg_flags
from mirage.commands.builtin.grep_binary import grep_input
from mirage.commands.builtin.grep_prefilter import required_literal
from mirage.commands.builtin.grep_scan import grep_stream
from mirage.commands.builtin.rg_search import Tally, search_haystack
from mirage.commands.spec import SPECS
from mirage.commands.spec.flag_view import FlagView
from mirage.io.async_line_iterator import AsyncLineIterator
from mirage.io.types import IOResult, materialize

PATTERNS = [
    r"zzqqxx",
    r"zzqqxx|qqzzyy",
    r"zz.qxx",
    r"\bzzqqxx\b",
    r"^zzqqxx$",
    r"zz[abc]qxx",
    r"(zzqqxx|qqzzyy)+",
    r"(zz)?qqxx",
    r"zzq{2,3}xx",
    r"zz\.qxx",
]


async def _run(engine, data, pat, flags, size=65536):

    async def source() -> AsyncIterator[bytes]:
        for at in range(0, len(data), size):
            yield data[at:at + size]

    io = IOResult(exit_code=1)
    if engine == "grep":
        f = grep_flags(FlagView(flags, spec=SPECS["grep"]), False)
        out = await materialize(grep_input(source(), pat, f, "f", True, io))
        return out, io.exit_code, io.stderr
    if engine == "rg":
        f = rg_flags(FlagView(flags, spec=SPECS["rg"]))
        tally = Tally()
        out = await materialize(
            search_haystack(source(), pat, f, "f", "f", tally))
        return out, tally.selected, None
    out = await materialize(grep_stream(source(), pat, count_only=True, io=io))
    return out, io.exit_code, io.stderr


@pytest.mark.asyncio
@pytest.mark.parametrize("record",
                         [b"abcdefg\n", b"abcdefg\0", b"\xffabcdef\n"])
@pytest.mark.parametrize("engine", ["grep", "rg", "stream"])
@pytest.mark.parametrize("pattern", PATTERNS)
@pytest.mark.parametrize("fold", [0, re.IGNORECASE])
@pytest.mark.parametrize("flags", [{}, {
    "c": True
}, {
    "args_l": True
}, {
    "q": True
}])
async def test_line_work_is_bounded_by_blocks(engine, pattern, fold, flags,
                                              record, monkeypatch):
    calls = 0
    method = "read_until" if engine == "rg" else "readline"
    original = getattr(AsyncLineIterator, method)

    async def counted(self, *args):
        nonlocal calls
        calls += 1
        assert calls < 50, "nonmatching blocks must skip per-line decoding"
        return await original(self, *args)

    monkeypatch.setattr(AsyncLineIterator, method, counted)
    out, selected, error = await _run(engine, record * 40000,
                                      re.compile(pattern, fold), flags)
    assert not error
    if engine == "rg":
        assert not selected and out == b""
    else:
        assert selected == 1
        assert out == (b"0\n" if engine == "stream" else
                       b"f:0\n" if flags.get("c") else b"")


@pytest.mark.asyncio
@pytest.mark.parametrize("engine", ["grep", "rg"])
@pytest.mark.parametrize("size", [7, 4096, 65536])
@pytest.mark.parametrize("flags", [
    {
        "n": True,
        "byte_offset": True
    },
    {
        "c": True
    },
    {
        "args_l": True
    },
    {
        "files_without_match": True
    },
    {
        "q": True
    },
    {
        "m": 1
    },
    {
        "o": True,
        "n": True,
        "byte_offset": True
    },
    {
        "v": True,
        "c": True
    },
    {
        "B": 2,
        "A": 1
    },
    {
        "stop_on_nonmatch": True
    },
    {
        "passthru": True
    },
])
async def test_skipping_preserves_output_status_and_boundaries(
        engine, size, flags, monkeypatch):
    data = (b"other\n" * 1000 + "é ZZQQXX 😀\nſ K İ ı\n".encode() +
            b"other\n" * 1000 + b"qqzzyy\nzz.qxx\nzz\xffqxx\nzz\0qxx\nqqxx")
    for pattern in [
            *PATTERNS, "s|k|i", "zzqqxx|", "zzq*", "[^z]", "(?=qq)qq",
            "(qq)\\1"
    ]:
        pat = re.compile(pattern, re.IGNORECASE)
        actual = await _run(engine, data, pat, flags, size)
        with monkeypatch.context() as m:
            m.setattr(AsyncLineIterator, "skip_nonmatching_lines",
                      lambda *args: (0, 0))
            expected = await _run(engine, data, pat, flags, size)
        assert actual == expected, pattern


@pytest.mark.parametrize("pattern", [
    "a*", "a?", "a{0,3}", "foo|", "[abc]", "(?i:foo)", r"(foo)\1", r"\x66oo",
    "(?=foo)", "(" * 40 + "foo" + ")" * 40
])
def test_unsupported_or_optional_patterns_fall_back(pattern):
    assert required_literal(re.compile(pattern)) is None


@pytest.mark.parametrize("pattern,match", [("s", "ſ"), ("k", "K"), ("i", "İ"),
                                           ("i", "ı")])
def test_unicode_case_folds_are_never_rejected(pattern, match):
    prefilter = required_literal(re.compile(pattern, re.IGNORECASE))
    assert isinstance(prefilter, re.Pattern)
    assert prefilter.search(match.encode())


def test_required_literals_retain_matches_across_regex_combinations():
    atoms = [
        "a", "b", "[ab]", ".", r"\w", "(?:a|b)", "(?:a|)", "(?=a)", "(?!b)",
        "(?<!b)"
    ]
    texts = [
        "".join(chars) for size in range(6)
        for chars in product("ab", repeat=size)
    ]
    for left, right in product(atoms, repeat=2):
        for repeat in ["", "?", "*", "+", "{0,2}", "{1,2}"]:
            if left.startswith("(?") and not left.startswith("(?:") and repeat:
                continue
            for pattern in [
                    f"{left}{repeat}{right}", f"(?:{left}{repeat}|{right})"
            ]:
                pat = re.compile(pattern, re.IGNORECASE)
                prefilter = required_literal(pat)
                for text in texts:
                    if prefilter is None or not pat.search(text):
                        continue
                    raw = text.encode()
                    assert (prefilter in raw if isinstance(prefilter, bytes)
                            else prefilter.search(raw)), (pattern, text)
