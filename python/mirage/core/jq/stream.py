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
from collections.abc import AsyncIterator, Sequence

import orjson

from mirage.core.jq.parse import (CLOSE_BRACE, CLOSE_BRACKET, OPEN_BRACE,
                                  OPEN_BRACKET, QUOTE, JqParser, decode_utf8,
                                  utf8_missing)
from mirage.core.jq.types import (NO_VALUE, UNKNOWN_POSITION, InputSource,
                                  JqOptions, JqParseError, NoValue)
from mirage.types import JsonValue

# The most bytes one read of jq's input reader takes (jq 1.8's util.c):
# fgets into a 4096-byte buffer, less the four bytes it keeps for UTF-8
# and the NUL. A read stops after a newline, and one that ends inside a
# character reads on to the end of it.
READ_CHUNK = 4091

WHITESPACE = b" \t\r\n"
CLOSERS = frozenset((QUOTE, CLOSE_BRACKET, CLOSE_BRACE))
OPENERS = frozenset((OPEN_BRACKET, OPEN_BRACE))

# orjson reads an integer past 64 bits as a float, where jq keeps every
# digit, so text holding one is left to jq's own parser. Only a whole
# integer counts: digits after a point or an exponent never make one.
LONG_INTEGER = re.compile(
    rb"(?<![0-9.eE])(?:-[0-9]{19,}|[0-9]{20,})(?![0-9.eE])")


def _loads(data: bytes) -> "JsonValue | NoValue":
    """One JSON value by orjson, when it reads the text exactly as jq's
    parser would, or NO_VALUE.

    Whatever orjson accepts, jq accepts as the same value, bar integers
    past 64 bits; what it refuses (jq's extra number forms, lone
    surrogates, invalid UTF-8, nesting past 1024) is jq's parser's to
    decide.

    Args:
        data (bytes): the text.
    """
    if LONG_INTEGER.search(data):
        return NO_VALUE
    try:
        return orjson.loads(data)
    except orjson.JSONDecodeError:
        return NO_VALUE


def _completion(data: bytes) -> int:
    """Where jq's parser holds the one value `data` spells whole: at its
    closing quote or bracket, or at the whitespace byte after a number or
    a literal. -1 for a number or a literal nothing follows, which jq
    completes only at the end of its input.

    Args:
        data (bytes): one value with the whitespace around it.
    """
    stop = len(data.rstrip(WHITESPACE))
    if data[stop - 1] in CLOSERS:
        return stop - 1
    return stop if stop < len(data) else -1


def pieces_through(data: bytes | bytearray, index: int) -> tuple[int, int]:
    """The reads jq's reader takes from the start of `data`, one piece at
    a time, until it holds byte `index`: where the last of them ends, and
    how many of them end in a newline, which is what its line count
    counts.

    Args:
        data (bytes | bytearray): an input's unread bytes, from a piece
            boundary on, through at least the piece holding `index`.
        index (int): the byte.
    """
    # A piece never runs past a newline, so each newline before the line
    # holding `index` ended a piece of its own.
    at = data.rfind(b"\n", 0, index) + 1
    lines = data.count(b"\n", 0, at)
    while True:
        newline = data.find(b"\n", at, at + READ_CHUNK)
        if newline >= 0:
            end = newline + 1
            lines += 1
        elif len(data) - at > READ_CHUNK:
            end = at + READ_CHUNK
            end = min(end + utf8_missing(data[at:end]), len(data))
        else:
            end = len(data)
        if end > index:
            return end, lines
        at = end


class InputReader:
    """jq's input reader (util.c) over every input of an invocation.

    One parser reads all of them, one after another, so a value can run
    on from one input into the next the way it does in jq (`1` then `2`
    read as `12`), and a parse error counts its lines across the inputs.
    The parser is fed the pieces jq's fgets reads, so the position a run
    reports, the input's name and the lines read of it, is jq's. Under -R
    the pieces make up the lines, which also run on from one input into
    the next when one lacks its final newline.

    A value orjson can read, one line of JSON Lines or a whole document,
    is taken in one step and handed to the parser as read (see _fast);
    everything else, bad input included, goes through jq's parser.

    Args:
        sources (Sequence[InputSource]): the inputs, in order.
        opts (JqOptions): resolved options; -R, -s, --seq and --stream
            decide how the inputs are read.
    """

    def __init__(self, sources: Sequence[InputSource],
                 opts: JqOptions) -> None:
        self._sources = list(sources)
        self._opened = 0
        self._parser = (None if opts.raw_input else JqParser(
            seq=opts.seq, streaming=opts.stream))
        self._fast_ok = not (opts.raw_input or opts.seq or opts.stream)
        self._slurped: "list[JsonValue] | str | NoValue" = NO_VALUE
        if opts.slurp:
            self._slurped = "" if opts.raw_input else []
        self._name: str | None = None
        self._line = 0
        self._chunks: AsyncIterator[bytes] | None = None
        self._pending = bytearray()
        self._drained = False
        self._feof = False
        self._whole_tried = False

    def position(self) -> str:
        """Where jq's reader stands, as its error reports word it: the
        current input and the lines read of it, or `<unknown>` before any
        input was opened."""
        if self._name is None:
            return UNKNOWN_POSITION
        return f"{self._name}:{self._line}"

    async def next_input(self) -> "JsonValue | JqParseError | NoValue":
        """The next value of the stream, the parse error that stops it,
        or NO_VALUE once it is used up (jq_util_input_next_input). Under
        -s the one value is the whole stream; a parse error comes back
        instead of it."""
        if self._parser is None:
            return await self._next_line()
        parser = self._parser
        is_last = False
        while True:
            if parser.remaining() == 0:
                if self._fast_ok and parser.clean():
                    fast = await self._fast(parser)
                    if fast is not NO_VALUE:
                        if not isinstance(self._slurped, list):
                            return fast
                        self._slurped.append(fast)
                        continue
                piece, is_last = await self._read_more()
                parser.feed(piece, not is_last)
            value = parser.next()
            if isinstance(self._slurped, list):
                if isinstance(value, JqParseError):
                    return value
                if value is not NO_VALUE:
                    self._slurped.append(value)
            elif value is not NO_VALUE:
                return value
            if is_last:
                break
        return self._take_slurped()

    async def _next_line(self) -> "JsonValue | NoValue":
        line: str | NoValue = NO_VALUE
        while True:
            piece, is_last = await self._read_more()
            if piece:
                if isinstance(self._slurped, str):
                    self._slurped += decode_utf8(piece)
                elif piece.endswith(b"\n"):
                    head = "" if line is NO_VALUE else line
                    return head + decode_utf8(piece[:-1])
                else:
                    line = (""
                            if line is NO_VALUE else line) + decode_utf8(piece)
            if is_last:
                break
        if isinstance(self._slurped, str):
            return self._take_slurped()
        return line

    def _take_slurped(self) -> "JsonValue | NoValue":
        slurped = self._slurped
        self._slurped = NO_VALUE
        return slurped

    async def _open_next(self) -> None:
        """Move on to the next input once the current one is read to its
        end, the first half of jq's read_more."""
        if self._chunks is not None and not self._feof:
            return
        self._chunks = None
        if self._opened < len(self._sources):
            source = self._sources[self._opened]
            self._opened += 1
            self._name = source.name
            self._line = 0
            self._chunks = source.chunks
            self._pending = bytearray()
            self._drained = False
            self._feof = False
            self._whole_tried = False

    async def _pull(self) -> None:
        assert self._chunks is not None
        chunk = await anext(self._chunks, None)
        if chunk is None:
            self._drained = True
        else:
            self._pending += chunk

    async def _read_more(self) -> tuple[bytes, bool]:
        """jq's read_more: the next piece of the input, and whether the
        stream is used up, which a piece comes back empty for."""
        await self._open_next()
        piece = b""
        if self._chunks is not None:
            piece = await self._read_piece()
        return piece, self._opened == len(
            self._sources) and self._chunks is None

    async def _read_piece(self) -> bytes:
        pending = self._pending
        while True:
            newline = pending.find(b"\n", 0, READ_CHUNK)
            if newline >= 0:
                piece = bytes(pending[:newline + 1])
                del pending[:newline + 1]
                self._line += 1
                return piece
            if len(pending) >= READ_CHUNK:
                piece = bytes(pending[:READ_CHUNK])
                del pending[:READ_CHUNK]
                missing = utf8_missing(piece)
                while missing and len(pending) < missing and not self._drained:
                    await self._pull()
                if missing:
                    piece += bytes(pending[:missing])
                    del pending[:missing]
                return piece
            if self._drained:
                piece = bytes(pending)
                pending.clear()
                self._feof = True
                return piece
            await self._pull()

    async def _fast(self, parser: JqParser) -> "JsonValue | NoValue":
        """Take the next value in one step when orjson reads it as jq
        would: the rest of the line, or else, where the line opens a
        document it does not close, the rest of the input. The parser is
        handed the bytes as read and the rest of the last piece, so the
        line count, the position and whatever follows are what jq's parser
        would have reached.

        Args:
            parser (JqParser): the stream's parser, clean (JqParser.clean).
        """
        await self._open_next()
        if self._chunks is None:
            return NO_VALUE
        newline = self._pending.find(b"\n")
        while newline < 0 and not self._drained:
            searched = len(self._pending)
            await self._pull()
            newline = self._pending.find(b"\n", searched)
        pending = self._pending
        if not pending:
            return NO_VALUE
        skip = parser.bom_skip(bytes(pending[:3]))
        if skip is None:
            return NO_VALUE
        if newline < 0 and self._opened < len(self._sources):
            return NO_VALUE
        end = newline + 1 if newline >= 0 else len(pending)
        line = bytes(pending[skip:end])
        value = _loads(line)
        if value is not NO_VALUE:
            stop = _completion(line)
            if stop < 0:
                return NO_VALUE
            return self._took(parser, value, skip, skip + stop)
        first = line.lstrip(WHITESPACE)[:1]
        if self._whole_tried or not first or first[0] not in OPENERS:
            return NO_VALUE
        self._whole_tried = True
        while not self._drained:
            await self._pull()
        rest = bytes(self._pending[skip:])
        value = _loads(rest)
        if value is NO_VALUE:
            return NO_VALUE
        stop = _completion(rest)
        if stop < 0:
            return NO_VALUE
        return self._took(parser, value, skip, skip + stop)

    def _took(self, parser: JqParser, value: JsonValue, skip: int,
              stop: int) -> JsonValue:
        pending = self._pending
        end, lines = pieces_through(pending, stop)
        parser.skip(pending, skip, stop + 1)
        rest = bytes(pending[stop + 1:end])
        del pending[:end]
        self._line += lines
        parser.feed(rest, True)
        return value


async def read_values(
        source: InputSource) -> tuple[list[JsonValue], JqParseError | None]:
    """Every value of one input, and the parse error that ended it early,
    as jq reads a --slurpfile.

    Args:
        source (InputSource): the input.
    """
    reader = InputReader([source], JqOptions())
    values: list[JsonValue] = []
    while True:
        value = await reader.next_input()
        if isinstance(value, JqParseError):
            return values, value
        if value is NO_VALUE:
            return values, None
        values.append(value)


def parse_value(text: bytes) -> "JsonValue | NoValue":
    """The one value a text holds, as jq's jv_parse reads an --argjson or
    a --jsonargs value, or NO_VALUE when it holds none, several, or bad
    JSON.

    Args:
        text (bytes): the text.
    """
    value = _loads(text)
    if value is not NO_VALUE:
        return value
    parser = JqParser()
    parser.feed(text, False)
    parsed = parser.next()
    if parsed is NO_VALUE or isinstance(parsed, JqParseError):
        return NO_VALUE
    if parser.next() is not NO_VALUE:
        return NO_VALUE
    return parsed


def is_jsonl_path(path: str) -> bool:
    """Whether a file's name says it holds JSON Lines, one document to a
    line, which jq reads one line at a time.

    Args:
        path (str): the file's path.
    """
    return path.endswith(".jsonl") or path.endswith(".ndjson")
