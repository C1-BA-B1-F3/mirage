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

import os
import tempfile
from pathlib import Path

import asyncssh

from mirage.concurrency.limiter import run_blocking
from mirage.workspace.record.disk import DiskRecordClient

HOST_KEY_ALGORITHM = "ssh-ed25519"


def _read_host_key(path: Path) -> asyncssh.SSHKey | None:
    try:
        return asyncssh.read_private_key(str(path))
    except FileNotFoundError:
        return None


def _write_host_key(path: Path, key: asyncssh.SSHKey) -> None:
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(key.export_private_key())
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


async def load_host_key(path: Path) -> asyncssh.SSHKey:
    """The daemon's SSH host key, minted on first use and kept.

    A fresh key per start would make every client's known_hosts entry
    look like a man-in-the-middle, so the first start writes one with
    owner-only permissions and every later start reads it back. Minting
    holds a lockfile beside the key and looks again under it, so two
    daemons starting at once agree on one key; the key is written whole
    and renamed into place, so a reader never sees a partial file. Only
    exclusive create and rename are needed, which every local
    filesystem has. A start killed while minting leaves its lock, which
    the next start takes over once the record client counts it stale.

    Args:
        path (Path): where the private key lives.

    Returns:
        asyncssh.SSHKey: the host key.
    """
    key = await run_blocking(_read_host_key, path)
    if key is not None:
        return key
    await run_blocking(
        path.parent.mkdir, parents=True, exist_ok=True, mode=0o700
    )
    records = DiskRecordClient(str(path.parent), "")
    lock = await records.lock(path.name)
    try:
        key = await run_blocking(_read_host_key, path)
        if key is not None:
            return key
        key = asyncssh.generate_private_key(HOST_KEY_ALGORITHM)
        await run_blocking(_write_host_key, path, key)
        return key
    finally:
        await records.unlock(path.name, lock)
