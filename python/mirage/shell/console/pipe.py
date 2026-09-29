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
from collections import deque
from collections.abc import AsyncIterator

from mirage.shell.console.job_console import JobConsole
from mirage.shell.console.types import Channel
from mirage.shell.errors import PipeClosed


class PipeConsole(JobConsole):
    """A single-reader pipe with a kernel-sized buffer.

    A write succeeds while the reader is open and the buffer has room, as
    in bash, where a producer that finishes before ``head`` closes keeps
    its status. A lazy source is pulled only after ``drain``, so closing
    after one chunk does not fetch another backend page first.
    """

    def __init__(self, pipe_stderr: bool = False) -> None:
        super().__init__()
        self._pipe_stderr = pipe_stderr
        self._chunks: deque[bytes] = deque()
        self._bytes = 0
        self._ended = False
        self._delivered = 0
        self._accepted = 0
        self._reader_closed = False
        self._failure: BaseException | None = None
        self._changed = asyncio.Event()

    async def emit(self, channel: Channel, data: bytes) -> None:
        if channel != Channel.STDOUT and not self._pipe_stderr:
            await super().emit(channel, data)
            return
        if not data:
            return
        while self._bytes >= 65536 and not self._reader_closed:
            self._changed.clear()
            await self._changed.wait()
        if self._reader_closed:
            raise PipeClosed()
        self._chunks.append(data)
        self._bytes += len(data)
        self._delivered += 1
        self._changed.set()

    async def drain(self) -> None:
        """Wait until the reader has taken every chunk or closed."""
        while self._accepted < self._delivered and not self._reader_closed:
            self._changed.clear()
            await self._changed.wait()

    @property
    def closed_reader(self) -> bool:
        return self._reader_closed

    def end(self, error: BaseException | None = None) -> None:
        if error is not None:
            self._failure = error
        self._ended = True
        self._changed.set()

    def close_reader(self) -> None:
        self._reader_closed = True
        self._chunks.clear()
        self._bytes = 0
        self._changed.set()

    async def stream(self) -> AsyncIterator[bytes]:
        try:
            while True:
                if self._chunks:
                    chunk = self._chunks.popleft()
                    self._bytes -= len(chunk)
                    self._changed.set()
                    yield chunk
                    self._accepted += 1
                    self._changed.set()
                elif self._ended:
                    if self._failure is not None:
                        raise self._failure
                    return
                else:
                    self._changed.clear()
                    await self._changed.wait()
        finally:
            self.close_reader()
