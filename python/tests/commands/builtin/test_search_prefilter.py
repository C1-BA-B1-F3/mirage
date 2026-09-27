import itertools
import re

import pytest

from mirage.commands.builtin.search_prefilter import search_prefilter


def admits(prefilter, text):
    return (prefilter is None or (prefilter in text if isinstance(
        prefilter, bytes) else prefilter.search(text) is not None))


@pytest.mark.parametrize('source', [
    'zzqqxx',
    'zzqqxx|qqzzyy',
    'zz.qxx',
    r'\bzzqqxx\b',
    '^(zzqqxx|qqzzyy)$',
    'optional?required',
    'x*required',
    'x{0,3}required',
    '[a-z]+required',
    '(?:foo|bar)+required',
    r'a\+b',
    'a{2,3}b',
    r'(?<!\w)(?:needle)(?!\w)',
    'a(?=b)',
])
@pytest.mark.parametrize('flags', [re.ASCII, re.ASCII | re.IGNORECASE])
def test_rejects_absent_required_literals(source, flags):
    prefilter = search_prefilter(re.compile(source, flags))
    assert prefilter is not None
    assert not admits(prefilter, b'nothing here\n' * 100)


@pytest.mark.parametrize('source', [
    'a*',
    'a?|b',
    'a{0,2}',
    '(?:)',
    r'(a)\1',
    r'\x61',
    'é',
])
def test_falls_back(source):
    assert search_prefilter(re.compile(source)) is None


@pytest.mark.parametrize('flags', [0, re.I, re.I | re.ASCII])
def test_never_rejects_matching_line(flags):
    atoms = [
        'a', 'bc', '[ab]', '.', r'\w', '(a|bc)', '(?:a|)', 'a?', 'a*', 'a+',
        'a{0,2}', 'a{2}', '^a', 'c$', r'\ba\b'
    ]
    lines = [
        '', 'a', 'A', 'bc', 'aa', 'abc', 'abbc', 'c', 'abcabc', ' bca ', 'éa',
        'K', 'ſ'
    ]
    for left, right in itertools.product(atoms, repeat=2):
        for source in [left + right, f'(?:{left}|{right})']:
            pat = re.compile(source, flags)
            prefilter = search_prefilter(pat)
            for line in lines:
                if pat.search(line):
                    assert admits(prefilter,
                                  f'miss\n{line}\nmiss'.encode()), (pat, line)


def test_unicode_folding():
    prefilter = search_prefilter(re.compile('s|k', re.I))
    assert admits(prefilter, 'ſ\n'.encode())
    assert admits(prefilter, 'K\n'.encode())


def test_bounded_analysis():
    assert search_prefilter(re.compile('(' * 100 + 'a' + ')' * 100)) is None
    assert search_prefilter(
        re.compile('|'.join(f'word{i}' for i in range(100)))) is None
