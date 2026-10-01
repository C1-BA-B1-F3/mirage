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

import errno
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from dataclasses import dataclass

from mirage.io.async_line_iterator import SharedInput
from mirage.shell.constants import FD_BOTH, FD_CLOSE
from mirage.shell.types import Redirect, RedirectKind
from mirage.types import PathSpec
from mirage.utils.errors import BadDescriptorError


def unsupported_descriptor(redirects: Iterable[Redirect]) -> int | None:
    """The first descriptor outside the signed 32-bit range, or None.

    Both slots count: the descriptor a redirect claims (`3>f`, `3<f`,
    `3>&1`, `3>&-`) and the one it duplicates from (`>&3`, `<&3`,
    `2>&3`). `&>`'s FD_BOTH and `>&-`'s FD_CLOSE are the two sentinels
    the parser spells with -1, and neither is a descriptor.

    An ambiguous redirect (``3>&word``) is skipped: bash refuses it in
    its own words before it judges the descriptor, and so does the
    installer.

    Args:
        redirects (Iterable[Redirect]): parsed redirects, in line order.
    """
    for r in redirects:
        if r.kind == RedirectKind.AMBIGUOUS:
            continue
        if not 0 <= r.fd < 2**31 and r.fd != FD_BOTH:
            return r.fd
        if (isinstance(r.target, int) and not 0 <= r.target < 2**31
                and r.target != FD_CLOSE):
            return r.target
    return None


def bad_descriptor_line(fd: int) -> bytes:
    """Bash's error for a closed descriptor, without the line-number prefix.

    Args:
        fd (int): the descriptor that was named.
    """
    return f"{fd}: Bad file descriptor\n".encode()


async def unreadable_stdin() -> AsyncIterator[bytes]:
    """Standard input that fails on its first read with EBADF.

    bash opens a command whose stdin is closed (``<&-``) or duplicated
    from a write-only descriptor (``0<&1``) all the same; the descriptor
    exists, and only a read of it fails. A command that never reads
    (``true 0<&1``) succeeds, and one that does reports
    ``<cmd>: -: Bad file descriptor`` and exits 1, which is what the
    chokepoint renders from the error this raises.
    """
    raise BadDescriptorError(errno.EBADF, "Bad file descriptor", "-")
    yield b""  # pragma: no cover - makes this an async generator


class FileInput(SharedInput):

    def __init__(self, description: "FileDescription", data: bytes) -> None:
        super().__init__(data)
        self.description = description

    def dup(self) -> "FileInput":
        return self


@dataclass
class FileDescription:
    scope: PathSpec
    append: bool = False
    opened: bool = False
    offset: int = 0
    source: FileInput | None = None
    emit: Callable[[bytes], Awaitable[None]] | None = None


@dataclass(frozen=True)
class Descriptor:
    identity: str
    append: bool = False
    source: SharedInput | None = None
    file: FileDescription | None = None
