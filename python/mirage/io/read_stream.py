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
import weakref
from collections.abc import AsyncIterator, Callable

from mirage.types import Limit

logger = logging.getLogger(__name__)


def cap_end(chunk: bytes, limit: Limit, emitted: int, lines: int) -> int:
    """How much of ``chunk`` a byte and line cap lets through.

    The one cut every lazy cap applies, so a capped stream and a capped
    whole read stop at the same byte.

    Args:
        chunk (bytes): the next piece of output.
        limit (Limit): the cap.
        emitted (int): bytes the cap already let through.
        lines (int): newlines the cap already let through.
    """
    end = len(chunk)
    if limit.max_bytes is not None:
        end = min(end, max(0, limit.max_bytes - emitted))
    if limit.max_lines is None:
        return end
    remaining = limit.max_lines - lines
    if remaining <= 0:
        return 0
    at = 0
    for _ in range(remaining):
        newline = chunk.find(b"\n", at, end)
        if newline < 0:
            return end
        at = newline + 1
    return at


def current_loop() -> asyncio.AbstractEventLoop | None:
    """The loop running this code, None outside one."""
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


def call_on_loop(loop: asyncio.AbstractEventLoop | None,
                 fn: Callable[[], None]) -> None:
    """Run ``fn`` on ``loop``'s thread, at once when already there.

    A finalizer runs wherever the collector does, which is not always
    the loop's thread (a FUSE or sync-bridge worker running a cyclic
    collection), and loop state (an ``asyncio.Event``, a task, the
    observer's log) is only touched from the loop's own thread, so a
    foreign thread hands ``fn`` over. With the loop gone there is no one
    left to hand it to, and it runs where it is.

    Args:
        loop (asyncio.AbstractEventLoop | None): the loop the caller
            belongs to, None when it was made outside one.
        fn (Callable[[], None]): what to run.
    """
    if loop is None or loop.is_closed() or current_loop() is loop:
        fn()
        return
    try:
        loop.call_soon_threadsafe(fn)
    except RuntimeError:
        fn()


class _Tally:
    """What a read moved, and who is told once it settles.

    Kept apart from the stream so the finalizer that settles a stream
    nobody closed holds this, never the stream itself.

    Args:
        moved (int): bytes the backend moved so far.
    """

    def __init__(self, moved: int) -> None:
        self.moved = moved
        self.settled = False
        self.callbacks: list[Callable[[int], None]] = []

    def settle(self) -> None:
        """Tell every callback once; each runs even if one before failed.

        The first failure is raised once all have run (a later one is
        logged), so one consumer's broken callback costs no other its
        record.
        """
        if self.settled:
            return
        self.settled = True
        callbacks, self.callbacks = self.callbacks, []
        failure: Exception | None = None
        for callback in callbacks:
            try:
                callback(self.moved)
            except Exception as exc:
                if failure is None:
                    failure = exc
                else:
                    logger.debug("read settle callback failed: %r", exc)
        if failure is not None:
            raise failure


class ReadStream:
    """A read the op door hands out while it is still arriving.

    The door pulls the first chunk before it returns one, so a read
    that cannot open (a missing path, a directory, a refusal) fails at
    the call exactly as a whole read does; the rest comes from the
    backend as the consumer pulls it. The stream counts what the
    backend moved, cuts at a truncating cap, and settles once: when
    the bytes end, when a pull fails, on ``aclose``, which a consumer
    that stops early calls to release the backend and the mount
    serving it, or when it is collected unclosed (an ``async for``
    that breaks never closes what it iterates), so the read is
    recorded with what it moved either way.

    Args:
        first (bytes | None): the chunk the door already pulled, None
            when the read was empty.
        source (AsyncIterator[bytes] | None): the rest of the read,
            None when nothing is left open.
    """

    def __init__(self, first: bytes | None,
                 source: AsyncIterator[bytes] | None) -> None:
        self._first = first
        self._source = source
        self._limit: Limit | None = None
        self._tally = _Tally(len(first) if first is not None else 0)
        self._emitted = 0
        self._lines = 0
        weakref.finalize(self, call_on_loop, current_loop(),
                         self._tally.settle)
        if source is None:
            self._tally.settle()

    @classmethod
    def whole(cls, data: bytes) -> "ReadStream":
        """A read already in hand, handed out as one chunk.

        Args:
            data (bytes): the whole answer.
        """
        return cls(data, None)

    def cap(self, limit: Limit) -> None:
        """Truncate what is handed out from here on at ``limit``.

        Args:
            limit (Limit): a truncating cap on bytes, lines, or both.
        """
        self._limit = limit

    def on_settle(self, callback: Callable[[int], None]) -> None:
        """Call ``callback`` with the bytes moved once the read settles.

        A read that has already settled answers at once. The callback
        must not hold the stream: it rides the finalizer that settles a
        stream nobody closed, and would keep that stream alive.

        Args:
            callback (Callable[[int], None]): told the moved count.
        """
        if self._tally.settled:
            callback(self._tally.moved)
            return
        self._tally.callbacks.append(callback)

    def __aiter__(self) -> "ReadStream":
        return self

    async def __anext__(self) -> bytes:
        chunk = self._first
        self._first = None
        if chunk is None:
            if self._source is None:
                raise StopAsyncIteration
            try:
                chunk = await self._source.__anext__()
            except BaseException:
                self._source = None
                self._tally.settle()
                raise
            self._tally.moved += len(chunk)
        if self._limit is None:
            return chunk
        end = cap_end(chunk, self._limit, self._emitted, self._lines)
        kept = chunk[:end]
        self._emitted += end
        self._lines += kept.count(b"\n")
        if end < len(chunk):
            logger.debug("vfs op output truncated at %r", self._limit)
            await self.aclose()
            if not kept:
                raise StopAsyncIteration
        return kept

    async def aclose(self) -> None:
        """Stop the read: close the backend and settle what it moved."""
        self._first = None
        source, self._source = self._source, None
        try:
            close = getattr(source, "aclose", None)
            if close is not None:
                await close()
        finally:
            self._tally.settle()
