import pytest

from mirage.shell.bytes import encode_text
from mirage.workspace.executor.builtins.printf.format import run_printf

# GNU pins taken in debian:stable-slim. `handle_printf` collapses the
# error list into one stderr blob and a status, so the list itself —
# order and count — is only observable here.

# bash 5.2.37 through `od -An -tx1`: the format reads \NNN, one to three
# octal digits, and a %b argument also reads \0NNN, a leading 0 and up
# to three more.
_OCTAL_PINS = [
    ("\\0003", "00 33", "03"),
    ("\\0", "00", "00"),
    ("\\00", "00", "00"),
    ("\\000", "00", "00"),
    ("\\0000", "00 30", "00"),
    ("\\08", "00 38", "00 38"),
    ("\\101", "41", "41"),
    ("\\1011", "41 31", "41 31"),
    ("\\0101", "08 31", "41"),
    ("\\400", "00", "00"),
    ("\\0400", "20 30", "00"),
]

# bash 5.2.37 under LC_ALL=C.UTF-8 through `od -An -tx1`: the format and
# a %b argument write \u and \U through u32toutf8, so a surrogate half
# and a value past Unicode come out UTF-8-shaped, and 0x80000000 and
# past come out as nothing.
_UNICODE_PINS = [
    ("\\uD800", "ed a0 80"),
    ("\\uDC80", "ed b2 80"),
    ("\\uDFFF", "ed bf bf"),
    ("\\uD83D\\uDE00", "ed a0 bd ed b8 80"),
    ("\\U00110000", "f4 90 80 80"),
    ("\\U0010FFFF", "f4 8f bf bf"),
    ("\\U7FFFFFFF", "fd bf bf bf bf bf"),
    ("\\U80000000", ""),
    ("\\UFFFFFFFF", ""),
    ("x\\UFFFFFFFFy", "78 79"),
    ("a\\u0000b", "61 00 62"),
    ("\\uDC80\\xff", "ed b2 80 ff"),
]


def _od(text: str) -> str:
    return encode_text(text).hex(" ")


def test_errors_come_back_as_a_list_in_argument_order():
    out, errors = run_printf("%d %d\n", ["abc", "def"])
    assert out == "0 0\n"
    assert errors == [
        "printf: abc: invalid number\n",
        "printf: def: invalid number\n",
    ]


def test_a_cycle_consuming_nothing_ends_the_reuse():
    # `a%%b` has no conversion, so the first cycle consumes no argument
    # and the excess args are dropped rather than looping forever.
    assert run_printf("a%%b\n", ["x", "y", "z"]) == ("a%b\n", [])


def test_empty_format_drops_every_argument():
    assert run_printf("", ["a", "b", "c"]) == ("", [])


def test_stop_from_b_suppresses_the_rest_of_the_format():
    assert run_printf("[%b][%s]\n", ["ab\\ccd", "tail"]) == ("[ab", [])


def test_stop_from_b_on_a_later_cycle_ends_every_cycle():
    assert run_printf("<%b>", ["one", "tw\\co", "three"]) == ("<one><tw", [])


@pytest.mark.parametrize("value,expected", [
    ("0.5", "0"),
    ("1.5", "2"),
    ("2.5", "2"),
    ("3.5", "4"),
])
def test_fixed_precision_rounds_half_to_even(value, expected):
    assert run_printf("%.0f", [value]) == (expected, [])


def test_a_missing_argument_is_the_empty_string_or_zero():
    assert run_printf("[%s][%d]", []) == ("[][0]", [])


@pytest.mark.parametrize("escape,in_format,in_b_arg", _OCTAL_PINS)
def test_octal_reads_three_digits_in_the_format_and_zero_plus_three_in_b(
        escape, in_format, in_b_arg):
    fmt_out, fmt_errors = run_printf(escape, [])
    b_out, b_errors = run_printf("%b", [escape])
    assert (_od(fmt_out), fmt_errors) == (in_format, [])
    assert (_od(b_out), b_errors) == (in_b_arg, [])


@pytest.mark.parametrize("escape,expected", _UNICODE_PINS)
def test_unicode_escapes_write_through_u32toutf8(escape, expected):
    fmt_out, fmt_errors = run_printf(escape, [])
    b_out, b_errors = run_printf("%b", [escape])
    assert (_od(fmt_out), fmt_errors) == (expected, [])
    assert (_od(b_out), b_errors) == (expected, [])
