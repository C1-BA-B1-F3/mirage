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
import codecs
import io
import logging
from collections.abc import Awaitable, Iterable, Iterator
from types import TracebackType
from typing import Self, TypeVar

from mirage.bridge.sync import run_async_from_sync
from mirage.ops import Ops
from mirage.runtime.constants import ABSENT_PATH
from mirage.runtime.handles.mode import parse_mode
from mirage.runtime.open import apply_open
from mirage.runtime.types import VFSEntry, VFSStat
from mirage.runtime.vfs import stat_row

T = TypeVar("T")
logger = logging.getLogger(__name__)
# `io.open`'s own sentinel for "whatever the platform default is". It is
# not a codec name, and pathlib passes it for every `read_text()` on an
# interpreter that is not in UTF-8 mode (which is any interpreter whose
# LC_CTYPE is already a UTF-8 locale, so: the normal case), so looking
# the caller's word up as a codec raised LookupError on the ordinary
# path the moment `io.open` was patched.
LOCALE_ENCODING = "locale"


class _OpsSurface:
    """The questions an open asks, put to the ``Ops`` facade.

    Args:
        ops (Ops): the facade the file reads and writes through.
        loop (asyncio.AbstractEventLoop | None): the loop that drives it.
    """

    def __init__(
        self, ops: Ops, loop: asyncio.AbstractEventLoop | None
    ) -> None:
        self._ops = ops
        self._loop = loop

    def stat_or_none(
        self, path: str, *, nofollow: bool = False
    ) -> VFSStat | None:
        try:
            row = run_async_from_sync(
                self._ops.stat(path, nofollow=nofollow), self._loop
            )
        except ABSENT_PATH:
            return None
        return stat_row(row)

    def listing_or_none(self, path: str) -> list[VFSEntry] | None:
        try:
            names = run_async_from_sync(self._ops.readdir(path), self._loop)
        except ABSENT_PATH:
            return None
        return [
            VFSEntry(path=name, size=0, is_dir=name.endswith("/"))
            for name in names
        ]

    def create(self, path: str) -> None:
        run_async_from_sync(self._ops.create(path), self._loop)

    def truncate(self, path: str) -> None:
        run_async_from_sync(self._ops.truncate(path, 0), self._loop)


class MirageFile:
    def __init__(
        self,
        ops: Ops,
        path: str,
        mode: str = "r",
        loop: asyncio.AbstractEventLoop | None = None,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> None:
        self._closed = True
        self._ops = ops
        self._path = path
        self._mode = mode
        self._loop = loop
        self._facts = parse_mode(mode)
        self._binary = self._facts.binary
        self._readable = self._facts.readable
        self._writable = self._facts.writable
        if self._binary:
            if encoding is not None:
                raise ValueError(
                    "binary mode doesn't take an encoding argument"
                )
            if errors is not None:
                raise ValueError("binary mode doesn't take an errors argument")
            if newline is not None:
                raise ValueError("binary mode doesn't take a newline argument")
        elif newline not in (None, "", "\n", "\r", "\r\n"):
            raise ValueError(f"illegal newline value: {newline!r}")
        # The sentinel resolves to mirage's own default rather than to
        # `locale.getencoding()`, so `open(p).read()` and
        # `Path(p).read_text()` agree about one file's bytes; a mount
        # stores utf-8 whatever the host's locale happens to be.
        if encoding is None or encoding == LOCALE_ENCODING:
            self._encoding = "utf-8"
        else:
            self._encoding = encoding
        self._errors = errors if errors is not None else "strict"
        self._newline = newline
        codecs.lookup(self._encoding)
        self._dirty = False
        self._buf: io.BytesIO | io.StringIO | None = None
        # The open's effect lands now, by the rule every door shares; a
        # refusal leaves the file closed, so nothing flushes behind it.
        apply_open(_OpsSurface(ops, loop), path, self._facts)
        self._closed = False

    def _run(self, coro: Awaitable[T]) -> T:
        return run_async_from_sync(coro, self._loop)

    def _load(self) -> io.BytesIO | io.StringIO:
        if self._buf is not None:
            return self._buf
        if self._facts.truncate or self._facts.exclusive:
            if self._binary:
                self._buf = io.BytesIO()
            else:
                self._buf = io.StringIO(newline=self._newline)
            return self._buf
        if self._facts.append:
            data = self._run(self._ops.read(self._path))
            if self._binary:
                self._buf = io.BytesIO(data)
            else:
                self._buf = io.StringIO(
                    data.decode(self._encoding, self._errors),
                    newline=self._newline,
                )
            self._buf.seek(0, 2)
            return self._buf
        data = self._run(self._ops.read(self._path))
        if self._binary:
            self._buf = io.BytesIO(data)
        else:
            self._buf = io.StringIO(
                data.decode(self._encoding, self._errors),
                newline=self._newline,
            )
        return self._buf

    def _check_closed(self) -> None:
        if self._closed:
            raise ValueError("I/O operation on closed file")

    def _read_buffer(self) -> io.BytesIO | io.StringIO:
        self._check_closed()
        if not self.readable():
            raise io.UnsupportedOperation("not readable")
        return self._load()

    def _write_buffer(self) -> io.BytesIO | io.StringIO:
        self._check_closed()
        if not self.writable():
            raise io.UnsupportedOperation("not writable")
        return self._load()

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def name(self) -> str:
        return self._path

    @property
    def mode(self) -> str:
        return self._mode

    def readable(self) -> bool:
        return self._readable

    def writable(self) -> bool:
        return self._writable

    def read(self, size: int = -1) -> bytes | str:
        return self._read_buffer().read(size)

    def readline(self) -> bytes | str:
        return self._read_buffer().readline()

    def readlines(self) -> list[bytes] | list[str]:
        return self._read_buffer().readlines()

    def write(self, data: bytes | str) -> int:
        buffer = self._write_buffer()
        if isinstance(buffer, io.BytesIO):
            if not isinstance(data, bytes):
                raise TypeError("a bytes-like object is required")
            written = buffer.write(data)
            self._dirty = True
            return written
        if not isinstance(data, str):
            raise TypeError("string argument expected")
        written = buffer.write(data)
        self._dirty = True
        return written

    def writelines(self, lines: Iterable[bytes] | Iterable[str]) -> None:
        for line in lines:
            self.write(line)

    def seek(self, offset: int, whence: int = 0) -> int:
        self._check_closed()
        return self._load().seek(offset, whence)

    def tell(self) -> int:
        self._check_closed()
        return self._load().tell()

    def flush(self) -> None:
        self._check_closed()
        if not self._dirty or self._buf is None:
            return
        val = self._buf.getvalue()
        if isinstance(val, str):
            val = val.encode(self._encoding, self._errors)
        self._run(self._ops.write(self._path, val))
        self._dirty = False

    def close(self) -> None:
        if self._closed:
            return
        try:
            self.flush()
        finally:
            self._closed = True
            if self._buf is not None:
                self._buf.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            logger.debug(
                "failed to close mounted file %s", self._path, exc_info=True
            )

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def __iter__(self) -> Iterator[bytes] | Iterator[str]:
        buffer = self._read_buffer()
        if isinstance(buffer, io.BytesIO):
            return iter(buffer)
        return iter(buffer)

    def __next__(self) -> bytes | str:
        buffer = self._read_buffer()
        if isinstance(buffer, io.BytesIO):
            return next(buffer)
        return next(buffer)
