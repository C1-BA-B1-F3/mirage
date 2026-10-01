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

from typing import Protocol, runtime_checkable


@runtime_checkable
class ObserverStore(Protocol):
    """Storage seam for the hidden recorder.

    A store holds the recorder's JSONL files keyed by path
    (``/<day>/<session>.jsonl``). Implementations are infra adapters
    (RAM, Redis, disk, opfs in TS); everything above this seam (the
    Observer queries, the /.bash_history view, the history builtin)
    is storage-agnostic.
    """

    async def append(self, path: str, data: bytes) -> None:
        """Append bytes to the file at path, creating it if missing.

        Args:
            path (str): File key, e.g. ``/<day>/<session>.jsonl``.
            data (bytes): Bytes to append.
        """
        ...

    async def write(self, path: str, data: bytes) -> None:
        """Overwrite the file at path (snapshot restore).

        Args:
            path (str): File key.
            data (bytes): Full new content.
        """
        ...

    async def read_all(self) -> dict[str, bytes]:
        """Read every stored file.

        Returns:
            dict[str, bytes]: Mapping of file key to content.
        """
        ...

    async def read_matching(self, suffix: str) -> dict[str, bytes]:
        """Read only the files whose key ends with suffix.

        Lets per-session queries skip fetching other sessions' logs
        on remote stores.

        Args:
            suffix (str): File-key suffix, e.g. ``/<session>.jsonl``.

        Returns:
            dict[str, bytes]: Mapping of matching key to content.
        """
        ...

    async def clear(self) -> None:
        """Delete every stored file (snapshot-restore rewind)."""
        ...

    async def close(self) -> None:
        """Release any held connections or handles."""
        ...


class ObserverStoreBase:
    """Shared ObserverStore behavior.

    Implementations only provide ``append``/``write``/
    ``read_matching``/``clear``; ``read_all`` is reading with the
    empty suffix (every key matches), and ``close`` defaults to a
    no-op for stores that hold no connections.
    """

    async def read_matching(self, suffix: str) -> dict[str, bytes]:
        raise NotImplementedError

    async def read_all(self) -> dict[str, bytes]:
        """Read every stored file.

        Returns:
            dict[str, bytes]: Mapping of file key to content.
        """
        return await self.read_matching("")

    async def close(self) -> None:
        """Release any held connections or handles."""


class RAMObserverStore(ObserverStoreBase):
    """In-memory ObserverStore backed by a plain dict (the default)."""

    def __init__(self) -> None:
        self.files: dict[str, bytearray] = {}

    async def append(self, path: str, data: bytes) -> None:
        """Append bytes to the file at path.

        Args:
            path (str): File key.
            data (bytes): Bytes to append.
        """
        if path not in self.files:
            self.files[path] = bytearray()
        self.files[path] += data

    async def write(self, path: str, data: bytes) -> None:
        """Overwrite the file at path.

        Args:
            path (str): File key.
            data (bytes): Full new content.
        """
        self.files[path] = bytearray(data)

    async def read_matching(self, suffix: str) -> dict[str, bytes]:
        """Read only the files whose key ends with suffix.

        Args:
            suffix (str): File-key suffix.

        Returns:
            dict[str, bytes]: Mapping of matching key to content.
        """
        return {
            k: bytes(v) for k, v in self.files.items() if k.endswith(suffix)
        }

    async def clear(self) -> None:
        """Delete every stored file (snapshot-restore rewind)."""
        self.files.clear()
