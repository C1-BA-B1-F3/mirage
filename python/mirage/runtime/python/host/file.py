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
import errno
import io
import logging
import os
from collections.abc import Iterable, Iterator
from types import TracebackType
from typing import TYPE_CHECKING, Self

from mirage.ops import Ops
from mirage.runtime.handles.chunked import ChunkedHandle
from mirage.runtime.handles.constants import READ_CHUNK
from mirage.runtime.handles.mode import parse_mode
from mirage.runtime.open import apply_open
from mirage.runtime.python.host.vfs import HostVFS

if TYPE_CHECKING:
    from _typeshed import WriteableBuffer

logger = logging.getLogger(__name__)
# `io.open`'s own sentinel for "whatever the platform default is". It is
# not a codec name, and pathlib passes it for every `read_text()` on an
# interpreter that is not in UTF-8 mode (which is any interpreter whose
# LC_CTYPE is already a UTF-8 locale, so: the normal case), so looking
# the caller's word up as a codec raised LookupError on the ordinary
# path the moment `io.open` was patched.
LOCALE_ENCODING = "locale"

# The whole file in memory, or a reader over a chunked handle.
_Buffer = io.BytesIO | io.StringIO | io.BufferedReader | io.TextIOWrapper


class _ChunkedRaw(io.RawIOBase):
    """A raw stream over a chunked handle, for ``io.BufferedReader``.

    Args:
        handle (ChunkedHandle): the read-only handle it reads through.
    """

    def __init__(self, handle: ChunkedHandle) -> None:
        super().__init__()
        self._handle = handle

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def readinto(self, buffer: "WriteableBuffer") -> int:
        chunk = self._handle.read(len(memoryview(buffer)))
        memoryview(buffer).cast("B")[: len(chunk)] = chunk
        return len(chunk)

    def seek(self, offset: int, whence: int = 0) -> int:
        pos = self._handle.seek(offset, whence)
        if pos is None:
            raise OSError(errno.EINVAL, os.strerror(errno.EINVAL))
        return pos

    def tell(self) -> int:
        return self._handle.pos


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
        self._door = HostVFS(ops, loop)
        self._path = path
        self._mode = mode
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
        self._buf: _Buffer | None = None
        # The open's effect lands now, by the rule every door shares; a
        # refusal leaves the file closed, so nothing flushes behind it.
        self._row = apply_open(self._door, path, self._facts)
        self._closed = False

    def _load(self) -> _Buffer:
        if self._buf is not None:
            return self._buf
        row = self._row
        if row is not None and not self._writable and row.size > READ_CHUNK:
            # The buffered and text layers CPython puts over a real file.
            handle = ChunkedHandle(
                path=self._path, size=row.size, fetch=self._read_chunk
            )
            buffered: io.BufferedReader = io.BufferedReader(
                _ChunkedRaw(handle)
            )
            reader: _Buffer = (
                buffered
                if self._binary
                else io.TextIOWrapper(
                    buffered,
                    encoding=self._encoding,
                    errors=self._errors,
                    newline=self._newline,
                )
            )
            self._buf = reader
            return reader
        # A handle that writes starts from the stored bytes: its flush
        # stores what it holds.
        data = (
            self._door.run(self._door.ops.read(self._path, raw=self._writable))
            if row is not None
            else b""
        )
        if self._binary:
            self._buf = io.BytesIO(data)
        else:
            self._buf = io.StringIO(
                data.decode(self._encoding, self._errors),
                newline=self._newline,
            )
        if self._facts.append:
            self._buf.seek(0, 2)
        return self._buf

    def _read_chunk(self, offset: int, size: int) -> bytes:
        return self._door.run(self._door.ops.read(self._path, offset, size))

    def _check_closed(self) -> None:
        if self._closed:
            raise ValueError("I/O operation on closed file")

    def _read_buffer(self) -> _Buffer:
        self._check_closed()
        if not self.readable():
            raise io.UnsupportedOperation("not readable")
        return self._load()

    def _write_buffer(self) -> io.BytesIO | io.StringIO:
        self._check_closed()
        if not self.writable():
            raise io.UnsupportedOperation("not writable")
        buffer = self._load()
        assert isinstance(buffer, io.BytesIO | io.StringIO)
        return buffer

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
        if not self._dirty or not isinstance(
            self._buf, io.BytesIO | io.StringIO
        ):
            return
        val = self._buf.getvalue()
        if isinstance(val, str):
            val = val.encode(self._encoding, self._errors)
        self._door.run(self._door.ops.write(self._path, val))
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
        if isinstance(buffer, io.BytesIO | io.BufferedReader):
            return iter(buffer)
        return iter(buffer)

    def __next__(self) -> bytes | str:
        buffer = self._read_buffer()
        if isinstance(buffer, io.BytesIO | io.BufferedReader):
            return next(buffer)
        return next(buffer)
