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

from mirage.shell.bytes import byte_char
from mirage.shell.escapes import code_point_text
from mirage.workspace.executor.builtins.echo.constants import (
    HEX,
    HEX_ESCAPE_DIGITS,
    OCT,
    SIMPLE_ESCAPES,
)


def interpret_escapes(text: str) -> tuple[str, bool]:
    """Process C-style escape sequences for echo -e.

    Single-pass to handle \\\\ correctly (\\\\b → \\b literal).
    Supports: \\\\, \\n, \\t, \\r, \\a, \\b, \\f, \\v, \\e and \\E (ESC),
    \\xHH (a byte), \\uHHHH and \\UHHHHHHHH (a code point),
    \\0NNN (octal), \\c (stop output).
    Unknown escapes like \\z pass through as \\z. Returns the text and
    whether \\c stopped the output, which also drops echo's newline.

    Args:
        text (str): the operands to print, joined by spaces.
    """
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] != "\\" or i + 1 >= n:
            out.append(text[i])
            i += 1
            continue
        ch = text[i + 1]
        if ch in SIMPLE_ESCAPES:
            out.append(SIMPLE_ESCAPES[ch])
            i += 2
        elif ch == "c":
            return "".join(out), True
        elif ch in HEX_ESCAPE_DIGITS:
            # \xHH names a byte; \uHHHH and \UHHHHHHHH name a code point
            limit = HEX_ESCAPE_DIGITS[ch]
            digits: list[str] = []
            j = i + 2
            while j < n and len(digits) < limit and text[j] in HEX:
                digits.append(text[j])
                j += 1
            if digits:
                value = int("".join(digits), 16)
                out.append(
                    byte_char(value) if ch == "x" else code_point_text(value)
                )
                i = j
            else:
                out.append("\\" + ch)
                i += 2
        elif ch == "0":
            # \0NNN — up to 3 octal digits
            digits = []
            j = i + 2
            while j < n and len(digits) < 3 and text[j] in OCT:
                digits.append(text[j])
                j += 1
            out.append(byte_char(int("".join(digits), 8)) if digits else "\0")
            i = j
        else:
            # unknown escape — pass through literally
            out.append("\\")
            out.append(ch)
            i += 2
    return "".join(out), False
