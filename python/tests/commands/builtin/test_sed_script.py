import pytest

from mirage.commands.builtin.sed_script import execute_program, parse_program
from mirage.shell.bytes import encode_text


def _sed(expr: str, text: str) -> str:
    return execute_program(text, parse_program(expr))


@pytest.mark.parametrize("expr,text,expected", [
    ("a one\\/two", "x\n", "x\none/two\n"),
    ("i one\\/two", "x\n", "one/two\nx\n"),
    ("c one\\/two", "x\n", "one/two\n"),
    ("/^bibtexurl:/a codeurl: 'https:\\/\\/github.com\\/u\\/r'",
     "bibtexurl: x\n", "bibtexurl: x\ncodeurl: 'https://github.com/u/r'\n"),
])
def test_text_drops_backslash_before_ordinary_char(expr, text, expected):
    assert _sed(expr, text) == expected


@pytest.mark.parametrize("expr,expected", [
    ("a one\\/two\\tthree", "x\none/two\tthree\n"),
    ("a x\\ny", "x\nx\ny\n"),
    ("a x\\\\y", "x\nx\\y\n"),
    ("a x\\by", "x\nxby\n"),
    ("a 1\\a2\\f3\\v4\\r5", "x\n1\x072\f3\v4\r5\n"),
])
def test_text_decodes_escapes(expr, expected):
    assert _sed(expr, "x\n") == expected


def test_text_decodes_numeric_and_control_escapes():
    assert _sed("a [\\d065][\\x41][\\o101][\\x4][\\xZ][\\d300]",
                "x\n") == "x\n[A][A][A][\x04][xZ][,]\n"
    assert _sed("a [\\cA][\\ca][\\c?][\\c\\\\]",
                "x\n") == "x\n[\x01][\x01][\x7f][\x1c]\n"
    with pytest.raises(ValueError,
                       match=r"recursive escaping after \\c not allowed"):
        _sed("a [\\c\\d]", "x\n")


def test_text_numeric_escapes_above_ascii_are_raw_bytes():
    out = _sed("a [\\xff][\\d200][\\o377][\\x80][\\xc3\\xa9][\\o400]", "x\n")
    assert encode_text(out) == (
        b"x\n[\xff][\xc8][\xff][\x80][\xc3\xa9][\x00]\n")


def test_text_final_c_escape_takes_closing_newline():
    assert _sed("a foo\\c", "x\ny\n") == "x\nfooJy\nfooJ"
    assert _sed("i foo\\c", "x\n") == "foo\nx\n"


@pytest.mark.parametrize("expr,expected", [
    ("a  \t foo", "x\nfoo\n"),
    ("a\\   foo", "x\n   foo\n"),
    ("a\\tfoo", "x\ntfoo\n"),
    ("a \\tfoo", "x\ntfoo\n"),
    ("a\\\\tfoo", "x\n\tfoo\n"),
])
def test_text_leading_blanks(expr, expected):
    assert _sed(expr, "x\n") == expected


@pytest.mark.parametrize("expr,expected", [
    ("a\\\n  l1\\\n  l2", "x\n  l1\n  l2\n"),
    ("i\\\nl1\\\nl2", "l1\nl2\nx\n"),
    ("a foo\\\nbar", "x\nfoo\nbar\n"),
])
def test_text_classic_form_and_continued_lines(expr, expected):
    assert _sed(expr, "x\n") == expected


@pytest.mark.parametrize("expr,text,expected", [
    ("1a foo\n2d", "x\ny\n", "x\nfoo\n"),
    ("1a foo; 2d", "x\ny\n", "x\nfoo; 2d\ny\n"),
    ("a int x = 1; echo bar", "x\n", "x\nint x = 1; echo bar\n"),
    ("1d\n$a foo   ", "x\ny\n", "y\nfoo   \n"),
])
def test_text_runs_to_newline(expr, text, expected):
    assert _sed(expr, text) == expected


@pytest.mark.parametrize("expr,text,expected", [
    ("a one\\/two\\", "x\n", "x\none\\/two\n"),
    ("a\\", "x\ny\n", "x\ny\n"),
    ("c\\", "x\ny\n", ""),
])
def test_text_undecoded_when_script_ends_on_backslash(expr, text, expected):
    assert _sed(expr, text) == expected


def test_text_refuses_missing_text_and_open_block():
    with pytest.raises(ValueError,
                       match="expected \\\\ after `a', `c' or `i'"):
        _sed("a", "x\n")
    with pytest.raises(ValueError, match="unmatched `{'"):
        _sed("1{a foo;}", "x\ny\n")
    assert _sed("1{a foo\n}", "x\ny\n") == "x\nfoo\ny\n"


@pytest.mark.parametrize("script,text,expected", [
    ("2b\ns/./X/", "a\nb\nc\nd\n", "X\nb\nX\nX\n"),
    ("1b\n$!d", "a\nb\nc\nd\n", "a\nd\n"),
    ("s/a/A/\nt\ns/./X/", "a\nb\n", "A\nX\n"),
    ("1b done\ns/./X/\n:done\ns/$/!/", "a\nb\n", "a!\nX!\n"),
])
def test_branch_and_label_end_at_newline(script, text, expected):
    assert _sed(script, text) == expected
