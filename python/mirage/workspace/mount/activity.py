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
import weakref
from collections.abc import AsyncGenerator, AsyncIterator, Callable

from mirage.io.cachable_iterator import CachableAsyncIterator
from mirage.io.read_stream import call_on_loop, current_loop
from mirage.io.stream import close_quietly
from mirage.io.types import ByteSource

Release = Callable[[], None]


class VFSActivity:
    """Calls and streams sharing a VFS, including removed aliases."""

    def __init__(self) -> None:
        self._count = 0
        self._idle = asyncio.Event()
        self._idle.set()

    def acquire(self) -> Callable[[], None]:
        self._count += 1
        self._idle.clear()
        released = False

        def release() -> None:
            nonlocal released
            if released:
                return
            released = True
            self._count -= 1
            if self._count == 0:
                self._idle.set()

        return release

    async def wait(self) -> None:
        await self._idle.wait()

    def hold(self, source: ByteSource) -> ByteSource:
        if isinstance(source, (bytes, bytearray)):
            return source
        if isinstance(source, CachableAsyncIterator):
            if source.exhausted:
                return source
            source.replace_source(ActivityStream(source.source,
                                                 self.acquire()))
            return source
        return ActivityStream(source, self.acquire())


class _Hold:
    """The mount hold a stream carries, kept apart from the stream.

    What the stream's finalizer is given: it must reach nothing that
    reaches the stream (a command's output can close over the result
    that holds it), or the finalizer's own reference keeps the stream
    alive for good.

    Args:
        release (Release): gives the mount's hold back.
    """

    def __init__(self, release: Release) -> None:
        self._release = release
        self.started = False
        self.released = False

    def release(self) -> None:
        """Give the hold back, once however many paths end the stream."""
        if self.released:
            return
        self.released = True
        self._release()


async def _releasing(source: AsyncIterator[bytes],
                     hold: _Hold) -> AsyncGenerator[bytes, None]:
    """Pull ``source``, and close it before the hold goes back.

    The ``finally`` is also what the event loop runs when a started
    stream is collected unclosed (its async-generator finalizer closes
    the generator on the loop's own thread, cycles included), so the
    backend's cleanup (a file handle, a connection) always comes first
    and an unmount the release lets through never closes the VFS under
    a body that is still open.

    A source that ended (its last pull answered or raised) is not
    closed again; only a stream left at a chunk is.

    Args:
        source (AsyncIterator[bytes]): the backend source.
        hold (_Hold): the stream's hold.
    """
    hold.started = True
    ended = False
    try:
        while True:
            try:
                chunk = await source.__anext__()
            except BaseException:
                ended = True
                raise
            yield chunk
    except StopAsyncIteration:
        return
    finally:
        try:
            if not ended:
                # Collected as part of a cycle, the source's own
                # generator may be closing in a task of its own; the
                # close is cleanup, never the stream's outcome.
                await close_quietly(source)
        finally:
            hold.release()


def _collected(loop: asyncio.AbstractEventLoop | None, hold: _Hold) -> None:
    """Give back the hold of a stream collected before its first pull.

    A started stream needs nothing here: collecting it closes its
    ``_releasing`` generator, whose ``finally`` releases. One never
    pulled opened nothing, so the hold is simply released, on the
    stream's own loop whichever thread collected it.

    Args:
        loop (asyncio.AbstractEventLoop | None): the loop the stream
            was made on.
        hold (_Hold): the stream's hold.
    """
    if not hold.started:
        call_on_loop(loop, hold.release)


class ActivityStream:
    """Release a stream's VFS on EOF, error, explicit close, or collection.

    A consumer that drops a stream without closing it would otherwise
    keep the mount busy for good, and unmount waits on that count with
    no bound; collection is the last point anything could still pull
    from it, so the backend is closed and the hold goes with it.
    """

    def __init__(self, source: AsyncIterator[bytes],
                 release: Callable[[], None]) -> None:
        self._inner = source.__aiter__()
        self._hold = _Hold(release)
        self._source = _releasing(self._inner, self._hold)
        self._pull_lock = asyncio.Lock()
        weakref.finalize(self, _collected, current_loop(), self._hold)

    def __aiter__(self) -> "ActivityStream":
        return self

    async def __anext__(self) -> bytes:
        async with self._pull_lock:
            try:
                return await self._source.__anext__()
            except BaseException:
                self._hold.release()
                raise

    async def aclose(self) -> None:
        async with self._pull_lock:
            try:
                if self._hold.started:
                    await self._source.aclose()
                else:
                    close = getattr(self._inner, "aclose", None)
                    if close is not None:
                        await close()
            finally:
                self._hold.release()
