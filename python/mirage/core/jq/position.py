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

from collections.abc import Sequence
from itertools import groupby
from operator import itemgetter

from mirage.core.jq.types import STDIN_NAME

# The most bytes one read of jq's input reader takes (jq 1.8's util.c):
# fgets into a 4096-byte buffer, less the four bytes it keeps for UTF-8
# and the NUL. A piece that would end inside a character reads on to the
# end of it, and the reader counts a line once it reads the piece that
# ends in the newline.
READ_CHUNK = 4091

# The characters that complete a value the moment the parser reads them.
# A number or a literal is complete only at the character after it.
CLOSERS = '"]}'


def value_end(text: str, stop: int) -> int:
    """Where jq's parser holds the whole of a value: at its closing quote
    or bracket, or else at the delimiter after it, which is
    ``len(text)`` at the end of the input.

    Args:
        text (str): the input's text.
        stop (int): the index just past the value's last character.
    """
    return stop - 1 if text[stop - 1] in CLOSERS else stop


def _utf8_width(ch: str) -> int:
    point = ord(ch)
    if point < 0x80:
        return 1
    if point < 0x800:
        return 2
    return 3 if point < 0x10000 else 4


def _last_piece(text: str, start: int, stop: int) -> int:
    """Where the last piece of the line ``text[start:stop]`` begins, the
    piece jq's reader counts the line at.

    Args:
        text (str): the input's text.
        start (int): the line's first index.
        stop (int): just past its newline.
    """
    # Four bytes at most to a character, so a short line is one piece.
    if stop - start <= READ_CHUNK // 4:
        return start
    line = text[start:stop]
    if line.isascii():
        return start + (stop - start - 1) // READ_CHUNK * READ_CHUNK
    piece = start
    size = 0
    for i, ch in enumerate(line, start):
        size += _utf8_width(ch)
        if size >= READ_CHUNK and i + 1 < stop:
            piece = i + 1
            size = 0
    return piece


def lines_read(text: str, ats: Sequence[int]) -> list[int]:
    """How many lines jq's reader has counted by the time it holds each
    index in ``ats``.

    The reader counts a newline once it has read the piece that ends in
    it, and it reads a line whole unless the line runs past READ_CHUNK
    bytes, so a value inside a long line reads as the line before it
    until the reader holds the line's last piece.

    Args:
        text (str): the input's text.
        ats (Sequence[int]): indices into it, in order, with
            ``len(text)`` for the end of the input.
    """
    counts: list[int] = []
    total = -1
    # The newlines before `start`, the line holding the last index
    # asked about, which is `prev`; `last` is where that line's last
    # piece begins, and -1 until it is looked up.
    newlines = start = prev = 0
    last = -1
    ends_line = False
    for at in ats:
        if at >= len(text):
            if total < 0:
                total = text.count("\n")
            counts.append(total)
            continue
        if at < prev:
            newlines = start = prev = 0
            last = -1
        skipped = text.count("\n", prev, at)
        if skipped:
            newlines += skipped
            start = text.rfind("\n", prev, at) + 1
            last = -1
        prev = at
        if last < 0:
            newline = text.find("\n", at)
            ends_line = newline >= 0
            stop = newline + 1 if ends_line else len(text)
            last = _last_piece(text, start, stop)
        counts.append(newlines + 1 if ends_line and at >= last else newlines)
    return counts


class InputPositions:
    """Where jq's reader stands once it has read each document of the
    input stream, and once it has read all of it, worded the way jq's
    error reports word it: the input as the command line named it
    (``<stdin>`` for standard input) and the lines read of it.

    The lines are counted the first time a position is asked for, which
    for most runs is never.

    Args:
        names (Sequence[str]): each input's name.
        texts (Sequence[str]): each input's text.
        marks (Sequence[tuple[int, int]]): for each document, its input
            and the index at which the reader holds all of it.
    """

    def __init__(self, names: Sequence[str], texts: Sequence[str],
                 marks: Sequence[tuple[int, int]]) -> None:
        self._names = list(names)
        self._texts = list(texts)
        self._marks = list(marks)
        self._counts: list[int] | None = None

    def _lines(self) -> list[int]:
        if self._counts is None:
            counts: list[int] = []
            for source, group in groupby(self._marks, key=itemgetter(0)):
                counts.extend(
                    lines_read(self._texts[source], [at for _, at in group]))
            self._counts = counts
        return self._counts

    def at(self, doc: int) -> str:
        """Where the reader stands once it has read one document.

        Args:
            doc (int): the document's index in the stream. One with no
                input of its own (a slurp of nothing) stands at the end.
        """
        if doc >= len(self._marks):
            return self.end()
        return f"{self._names[self._marks[doc][0]]}:{self._lines()[doc]}"

    def end(self) -> str:
        """Where the reader stands once it has read the whole input."""
        if not self._names:
            return f"{STDIN_NAME}:0"
        newlines = self._texts[-1].count("\n")
        return f"{self._names[-1]}:{newlines}"
