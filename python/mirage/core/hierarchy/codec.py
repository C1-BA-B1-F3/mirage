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
from collections.abc import Callable
from dataclasses import dataclass

from mirage.utils.sanitize import (
    ESCAPE_LEAD,
    SAFE_SLASH,
    is_blank,
    path_safe_name,
)

_ASCII_DIGITS = re.compile(r"^[0-9]+$")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def iso_date_shaped(text: str) -> bool:
    """Whether the text is shaped like a YYYY-MM-DD date.

    Shape only, not a calendar check: the dated-message backends mint
    their date directories from real timestamps, so a shaped-but-absent
    date resolves through the listing like any other name. A backend
    that must refuse impossible dates (gcal, whose day dirs exist by
    construction) validates with its own calendar-aware check instead.

    Args:
        text (str): decoded segment payload.
    """
    return _ISO_DATE.match(text) is not None


def ascii_digits(text: str) -> bool:
    """Whether the text is a plain ASCII integer.

    ``int()`` also accepts unicode digits and TS ``parseInt`` accepts a
    digit-prefixed tail, so this is the one spelling both languages can
    agree on for numeric path segments.

    Args:
        text (str): decoded segment payload.
    """
    return _ASCII_DIGITS.match(text) is not None


def _path_safe_encode(value: str) -> str:
    """Render a free-form value as one segment ``_path_safe_decode`` inverts.

    ``/`` renders as ``∕`` the way ``path_safe_name`` renders it, and a
    value already holding ``∕`` or ``⁄`` has that character prefixed
    with ``⁄``. A blank value (``is_blank``, the one definition of white
    space both runtimes read) takes the lead too, so it renders as the
    lead plus its own characters (the empty value is the lone lead)
    rather than as ``path_safe_name``'s ``unknown``; ``path_safe_name``
    itself leads a dot-led name, which the decode's escape rule already
    inverts. The decode reads the segment back one token at a time, so
    no two values render as one segment. Without the escape ``a/b`` and
    ``a∕b`` would list as the same directory, and descending into it
    would filter for only one.

    Args:
        value (str): the raw value.
    """
    escaped = value.replace(ESCAPE_LEAD, ESCAPE_LEAD + ESCAPE_LEAD)
    escaped = escaped.replace(SAFE_SLASH, ESCAPE_LEAD + SAFE_SLASH)
    if is_blank(escaped):
        escaped = ESCAPE_LEAD + escaped
    return path_safe_name(escaped)


def _path_safe_decode(name: str) -> str:
    """Undo ``_path_safe_encode``.

    ``∕`` reads as ``/`` and ``⁄`` as an escape for the character after
    it; a lead with nothing after it escapes nothing, which is how the
    empty value's lone lead reads back as empty and how a glob head cut
    inside an escape pair loses only the dangling lead.

    Args:
        name (str): the rendered segment.
    """
    chars: list[str] = []
    escaped = False
    for char in name:
        if escaped:
            chars.append(char)
            escaped = False
        elif char == ESCAPE_LEAD:
            escaped = True
        elif char == SAFE_SLASH:
            chars.append("/")
        else:
            chars.append(char)
    return "".join(chars)


@dataclass(frozen=True, slots=True)
class Codec:
    """How one dynamic path segment encodes its value.

    Args:
        suffix (str): extension the segment carries (".json"); empty for
            bare names.
        validate (Callable | None): extra shape check on the decoded
            payload; a failing payload means the segment does not match
            the scope at all.
        path_safe (bool): the payload is a free-form value rendered
            path-safe and reversibly: ``/`` becomes ``∕`` (U+2215), a
            value already holding ``∕`` or ``⁄`` (U+2044) has that
            character prefixed with ``⁄``, and a blank or dot-led value
            is prefixed with ``⁄`` as well, so every value has a segment
            that lists, opens and ``decode``s back to exactly what
            ``encode`` rendered. The group levels of the table-shaped backends
            (qdrant, lancedb) are this shape: a segment there becomes
            an equality filter, so it has to name exactly one value.
    """

    suffix: str = ""
    validate: Callable[[str], bool] | None = None
    path_safe: bool = False

    def decode(self, text: str) -> str | None:
        """Decode a path segment, None when it does not fit.

        Args:
            text (str): raw path segment.
        """
        if self.suffix:
            if not text.endswith(self.suffix):
                return None
            text = text[: -len(self.suffix)]
        if not text:
            return None
        if self.path_safe:
            text = _path_safe_decode(text)
        if self.validate is not None and not self.validate(text):
            return None
        return text

    def encode(self, value: str) -> str:
        """Render a value back into a path segment.

        Args:
            value (str): decoded payload.
        """
        if self.path_safe:
            value = _path_safe_encode(value)
        return f"{value}{self.suffix}"

    def prefix_value(self, prefix: str) -> str:
        """The value prefix a rendered-name prefix stands for.

        What a backend pushes into its query when a glob's literal head
        narrows a listing: every value whose rendering starts with
        ``prefix`` starts with this, so the pushdown loses nothing, and
        the caller keeps only the rendered names that really start
        with ``prefix``. A head cut inside an escape pair ends on a
        lead that could open either escaped character; the decode drops
        it.

        Args:
            prefix (str): the literal head of a glob, in rendered form.
        """
        if not self.path_safe:
            return prefix
        return _path_safe_decode(prefix)


RAW = Codec()
JSON_NAME = Codec(suffix=".json")
JSONL_NAME = Codec(suffix=".jsonl")
INT_JSON = Codec(suffix=".json", validate=ascii_digits)
DATE = Codec(validate=iso_date_shaped)
PATH_SAFE = Codec(path_safe=True)
