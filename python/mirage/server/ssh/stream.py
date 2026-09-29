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

import asyncio
import logging
from collections import deque
from collections.abc import Awaitable, Callable
from enum import Enum

import asyncssh
from asyncssh.editor import SSHLineEditorChannel

from mirage.io.cooperative import chunks
from mirage.io.types import ByteSource

logger = logging.getLogger(__name__)

ENCODING = "utf-8"
# asyncssh runs its line editor only on a text channel, and
# surrogateescape is the one error policy under which every byte
# survives the str round trip, so binary input and output cross a text
# channel unchanged.
ERRORS = "surrogateescape"
READ_SIZE = 64 * 1024
# How far the client may type or pipe ahead of whoever reads it before
# the channel stops being read and SSH flow control pushes back.
MAX_BUFFERED = 1024 * 1024
MAX_LINE = 1024 * 1024
MAX_TERMINAL_LINE = 1024

Send = Callable[[bytes, bool], Awaitable[None]]


class Mark(Enum):
    """A control or input limit delivered in band with channel input."""

    EOF = "eof"
    INTERRUPT = "interrupt"
    LIMIT = "limit"


def encode(text: str) -> bytes:
    return text.encode(ENCODING, ERRORS)


def decode(data: bytes) -> str:
    return data.decode(ENCODING, ERRORS)


class ChannelInput:
    """Everything the client sends on one channel, read once, in order.

    One pump task reads the channel into a buffer, so the prompt and the
    running line's stdin draw from a single ordered stream (typeahead
    survives a command that did not read it), and an interrupt is seen
    even while nothing is reading. Ctrl-D from asyncssh's line editor
    ends input for one reader, as a terminal's does; the channel's own
    EOF ends it for good.

    Args:
        process (asyncssh.SSHServerProcess[str]): the channel's process.
    """

    def __init__(self, process: asyncssh.SSHServerProcess[str]) -> None:
        self._process = process
        self._items: deque[bytes | Mark] = deque()
        self._buffered = 0
        self._closed = False
        self._changed = asyncio.Event()
        self._room = asyncio.Event()
        self._room.set()
        self._interrupt: Callable[[], None] | None = None
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._pump())

    async def close(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        await asyncio.wait([self._task])
        if not self._task.cancelled() and self._task.exception():
            logger.warning("ssh: input pump failed: %r",
                           self._task.exception())

    def on_interrupt(self, handler: Callable[[], None] | None) -> None:
        """Route Ctrl-C (a break) or an INT signal to ``handler``.

        With no handler, the interrupt is queued in band for the prompt
        to read, and the line editor's half-typed input is dropped.

        Args:
            handler (Callable[[], None] | None): called on the channel's
                loop for each interrupt, or None to queue them.
        """
        self._interrupt = handler

    async def _pump(self) -> None:
        stdin = self._process.stdin
        while True:
            await self._room.wait()
            try:
                data = await stdin.read(READ_SIZE)
            except (asyncssh.BreakReceived, asyncssh.SignalReceived):
                self._interrupted()
                continue
            except asyncssh.TerminalSizeChanged:
                continue
            except (asyncssh.Error, OSError) as exc:
                logger.debug("ssh: channel input ended: %r", exc)
                break
            if data:
                self._push(encode(data))
            elif stdin.at_eof():
                break
            else:
                self._push(Mark.EOF)
        self._closed = True
        self._changed.set()

    def _interrupted(self) -> None:
        if self._interrupt is not None:
            self._interrupt()
            return
        chan = self._process.channel
        if isinstance(chan, SSHLineEditorChannel):
            chan.clear_input()
        self._push(Mark.INTERRUPT)

    def _push(self, item: bytes | Mark) -> None:
        self._items.append(item)
        self._buffered += len(item) if isinstance(item, bytes) else 1
        if self._buffered >= MAX_BUFFERED:
            self._room.clear()
        self._changed.set()

    def _took(self, size: int) -> None:
        self._buffered -= size
        if self._buffered < MAX_BUFFERED:
            self._room.set()

    async def _wait(self) -> None:
        self._changed.clear()
        await self._changed.wait()

    async def readline(self) -> bytes | Mark:
        """The next line, with its newline, or the control that came first.

        Returns:
            bytes | Mark: the line (a final unterminated one at the
                channel's EOF is returned as is), ``Mark.INTERRUPT`` for
                a Ctrl-C typed at the prompt, or ``Mark.EOF`` for Ctrl-D
                or the channel's EOF; ``Mark.LIMIT`` for an oversized line.
        """
        line = bytearray()
        while True:
            while self._items:
                item = self._items[0]
                if isinstance(item, Mark):
                    if line:
                        return bytes(line)
                    self._items.popleft()
                    self._took(1)
                    return item
                cut = item.find(b"\n")
                size = len(item) if cut < 0 else cut
                if len(line) + size > MAX_LINE:
                    return Mark.LIMIT
                if cut < 0:
                    self._items.popleft()
                    self._took(len(item))
                    line += item
                    continue
                self._took(cut + 1)
                line += item[:cut + 1]
                rest = item[cut + 1:]
                if rest:
                    self._items[0] = rest
                else:
                    self._items.popleft()
                return bytes(line)
            if self._closed:
                return bytes(line) if line else Mark.EOF
            await self._wait()

    async def read(self) -> bytes:
        """The next buffered chunk, for a running line's stdin.

        Returns:
            bytes: the chunk, or ``b""`` at Ctrl-D or the channel's EOF.
        """
        while True:
            if self._items:
                item = self._items.popleft()
                if isinstance(item, Mark):
                    self._took(1)
                if item is Mark.EOF:
                    return b""
                if isinstance(item, bytes):
                    self._took(len(item))
                    return item
                continue
            if self._closed:
                return b""
            await self._wait()


class ChannelOutput:
    """Writes a line's output back to the client.

    On a terminal stderr folds into stdout, as a pty points both
    descriptors at one device; asyncssh's line editor then turns each
    newline into CRLF and redraws the input line around the output.

    Args:
        process (asyncssh.SSHServerProcess[str]): the channel's process.
        tty (bool): whether the client asked for a terminal.
    """

    def __init__(self, process: asyncssh.SSHServerProcess[str],
                 tty: bool) -> None:
        self._process = process
        self._tty = tty

    async def write(self, data: bytes, stderr: bool = False) -> None:
        stream = (self._process.stderr
                  if stderr and not self._tty else self._process.stdout)
        stream.write(decode(data))
        await stream.drain()


class LoopStdin:
    """A channel's input as a line's stdin, pulled from the workspace loop.

    The line runs on the workspace runner's loop while the channel lives
    on the daemon's, so each pull hops to the daemon loop for the next
    buffered chunk and waits there.

    Args:
        source (ChannelInput): the channel's input.
        loop (asyncio.AbstractEventLoop): the loop the channel lives on.
    """

    def __init__(self, source: ChannelInput,
                 loop: asyncio.AbstractEventLoop) -> None:
        self._source = source
        self._loop = loop

    def __aiter__(self) -> "LoopStdin":
        return self

    async def __anext__(self) -> bytes:
        data = await asyncio.wrap_future(
            asyncio.run_coroutine_threadsafe(self._source.read(), self._loop))
        if not data:
            raise StopAsyncIteration
        return data


def loop_sender(output: ChannelOutput,
                loop: asyncio.AbstractEventLoop) -> Send:
    """A writer the workspace loop can await, landing on the channel's loop.

    Awaiting it waits for the channel to drain, so a fast producer is
    paced by the client instead of buffered without bound.

    Args:
        output (ChannelOutput): the channel's output.
        loop (asyncio.AbstractEventLoop): the loop the channel lives on.

    Returns:
        Send: ``send(data, stderr)``.
    """

    async def send(data: bytes, stderr: bool) -> None:
        await asyncio.wrap_future(
            asyncio.run_coroutine_threadsafe(output.write(data, stderr), loop))

    return send


async def deliver(stdout: ByteSource | None, stderr: ByteSource | None,
                  send: Send) -> None:
    """Stream a line's stdout, then its stderr, through ``send``.

    Args:
        stdout (ByteSource | None): the line's stdout.
        stderr (ByteSource | None): the line's stderr.
        send (Send): where each chunk goes.
    """
    for source, is_stderr in ((stdout, False), (stderr, True)):
        if source is None:
            continue
        async for chunk in chunks(source):
            if chunk:
                await send(chunk, is_stderr)
