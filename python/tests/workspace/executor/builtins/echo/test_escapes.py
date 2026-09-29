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

from mirage.shell.bytes import encode_text
from mirage.workspace.executor.builtins.echo import interpret_escapes


def test_newline():
    assert interpret_escapes("a\\nb") == ("a\nb", False)


def test_tab():
    assert interpret_escapes("a\\tb") == ("a\tb", False)


def test_carriage_return():
    assert interpret_escapes("\\r") == ("\r", False)


def test_bell():
    assert interpret_escapes("\\a") == ("\a", False)


def test_backspace():
    assert interpret_escapes("\\b") == ("\b", False)


def test_form_feed():
    assert interpret_escapes("\\f") == ("\f", False)


def test_vertical_tab():
    assert interpret_escapes("\\v") == ("\v", False)


def test_literal_backslash():
    assert interpret_escapes("a\\\\b") == ("a\\b", False)


def test_double_backslash_before_n():
    assert interpret_escapes("\\\\n") == ("\\n", False)


def test_double_backslash_before_b():
    assert interpret_escapes("a\\\\b") == ("a\\b", False)


def test_hex_escape():
    assert interpret_escapes("\\x41") == ("A", False)


def test_hex_single_digit():
    assert interpret_escapes("\\x9") == ("\t", False)


def test_hex_no_digits():
    assert interpret_escapes("\\x") == ("\\x", False)


def test_octal_escape():
    assert interpret_escapes("\\0101") == ("A", False)


def test_octal_null():
    assert interpret_escapes("\\0") == ("\0", False)


def test_stop_output():
    assert interpret_escapes("hello\\cworld") == ("hello", True)


def test_unknown_escape_passthrough():
    assert interpret_escapes("\\z") == ("\\z", False)


def test_no_escapes():
    assert interpret_escapes("hello world") == ("hello world", False)


def test_empty():
    assert interpret_escapes("") == ("", False)


def test_trailing_backslash():
    assert interpret_escapes("end\\") == ("end\\", False)


def test_mixed():
    assert interpret_escapes("a\\tb\\nc\\\\d") == ("a\tb\nc\\d", False)


# Pinned against bash 5.2.37 in docker (debian:stable-slim,
# LC_ALL=C.UTF-8): echo -e '<text>' | od -An -tx1.


def test_e_and_capital_e_are_esc():
    assert interpret_escapes("a\\eb\\Ec") == ("a\x1bb\x1bc", False)


def test_esc_at_the_end_of_the_text():
    assert interpret_escapes("a\\e") == ("a\x1b", False)
    assert interpret_escapes("a\\E") == ("a\x1b", False)


def test_esc_before_stop():
    assert interpret_escapes("a\\E\\cb") == ("a\x1b", True)
    assert interpret_escapes("a\\E\\c") == ("a\x1b", True)


def test_stop_before_esc():
    assert interpret_escapes("a\\c\\Eb") == ("a", True)


def test_double_backslash_before_e():
    assert interpret_escapes("\\\\e\\\\E") == ("\\e\\E", False)


def test_unicode_escape_is_a_code_point():
    assert interpret_escapes("\\u00e9") == ("é", False)
    assert interpret_escapes("\\U0001F600") == ("\U0001F600", False)


def test_unicode_escape_reads_at_most_its_digits():
    assert interpret_escapes("\\u0041B") == ("AB", False)
    assert interpret_escapes("\\u41") == ("A", False)
    assert interpret_escapes("\\U41") == ("A", False)


def test_unicode_escape_without_digits_is_literal():
    assert interpret_escapes("\\u") == ("\\u", False)
    assert interpret_escapes("\\ug") == ("\\ug", False)
    assert interpret_escapes("\\U") == ("\\U", False)


def test_unicode_nul_is_written():
    assert interpret_escapes("a\\u0000b") == ("a\0b", False)


def test_unicode_escape_outside_unicode_is_utf8_shaped():
    assert encode_text(interpret_escapes("\\uD800")[0]) == b"\xed\xa0\x80"
    assert encode_text(
        interpret_escapes("\\U00110000")[0]) == b"\xf4\x90\x80\x80"
    assert interpret_escapes("\\UFFFFFFFF") == ("", False)
