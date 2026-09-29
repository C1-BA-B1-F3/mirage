import re

import pytest

from mirage.utils.posix import (class_characters, compile_posix_regex,
                                translate_classes)


@pytest.mark.parametrize('name,yes,no', [
    ('alnum', 'aZ09', '_! '),
    ('alpha', 'aZ', '09_'),
    ('blank', ' \t', '\nA'),
    ('cntrl', '\x00\x1f\x7f', ' A'),
    ('digit', '09', 'aF_'),
    ('graph', '!AZ09~', ' \t'),
    ('lower', 'az', 'AZ0'),
    ('print', ' AZ09~', '\t\n'),
    ('punct', '![]-_', 'aZ0 '),
    ('space', ' \t\n\r\f\v', 'a0'),
    ('upper', 'AZ', 'az0'),
    ('xdigit', '09aAfF', 'gG_'),
])
def test_class_membership(name, yes, no):
    compiled = re.compile(translate_classes(f'^[[:{name}:]]$'))
    expanded = class_characters(name)
    for char in yes:
        assert compiled.fullmatch(char)
        assert char in expanded
    for char in no:
        assert not compiled.fullmatch(char)
        assert char not in expanded


def test_class_order_for_translation():
    assert class_characters('space') == '\t\n\v\f\r '
    assert class_characters('lower') == 'abcdefghijklmnopqrstuvwxyz'


@pytest.mark.parametrize('pattern',
                         ['[[:bogus:]]', '[[:constructor:]]', '[[:digit:]'])
def test_invalid_classes_refused(pattern):
    with pytest.raises(re.error):
        translate_classes(pattern)


def test_escapes_and_mixed_brackets():
    assert re.fullmatch(translate_classes(r'\[\[:digit:\]\]'), '[[:digit:]]')
    compiled = re.compile(translate_classes('^[][:digit:]_]+$'))
    assert compiled.fullmatch(']_123')
    assert not compiled.fullmatch('abc')


@pytest.mark.parametrize('pattern,nested', [
    ('a++', '(?:a+)+'),
    ('a+?', '(?:a+)?'),
    ('a{1,2}?', '(?:a{1,2})?'),
    ('(ab)+?', '(?:(ab)+)?'),
    ('a|[bc]**', 'a|(?:[bc]*)*'),
    (r'\++', r'\++'),
    ('a{', 'a{'),
])
def test_stacked_quantifiers_nest(pattern, nested):
    assert translate_classes(pattern) == nested
    assert translate_classes(pattern, nest=False) == pattern


def test_nested_quantifier_keeps_backtracking():
    assert re.sub(translate_classes('a+?'), 'X', 'aaa', count=1) == 'X'
    assert re.fullmatch(translate_classes('a++a'), 'aaa')


@pytest.mark.parametrize("source,text,expected",
                         [('élan', 'ÉLAN', False), ('Élan', 'ÉLAN', True),
                          ('σ', 'Σ', False), ('k', 'K', False),
                          ('i', 'İ', False), ('s', 'ſ', False),
                          ('[A-Z]+', 'MiXeD', True), ('[^A-Z]', 'a', False),
                          ('[^a]', 'A', False), ('[Z-a]+', 'ZA[', True),
                          ('[Z-a]', 'B', False), ('[É]', 'é', False),
                          ('[^É]', 'é', True), ('\\D[A-Z]', '!a', True),
                          ('\\x41\\u0042', 'ab', True),
                          ('([A-Z]+)-\\1', 'Ab-aB', True),
                          ('(É)-\\1', 'É-é', False), ('(É)-\\1', 'É-É', True)])
def test_ascii_case_folding(source, text, expected):
    assert bool(compile_posix_regex(source,
                                    re.IGNORECASE).fullmatch(text)) == expected


def test_ascii_captures_preserve_spelling():
    pattern = compile_posix_regex(r"(a)(b)", re.IGNORECASE)
    assert pattern.sub(r"\2\1", "Ab aB") == "bA Ba"


@pytest.mark.parametrize("flags", [0, re.IGNORECASE])
def test_c_locale_whitespace(flags):
    for source in [r"\s", r"[\s]", r"[^\S]"]:
        assert compile_posix_regex(source, flags).search(" ")
        assert not compile_posix_regex(source, flags).search("\u00a0")
    assert compile_posix_regex(r"\S", flags).search("\u00a0")
    assert compile_posix_regex(r"\\s", flags).search(r"\s")
