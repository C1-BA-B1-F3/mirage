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
from pathlib import Path

import asyncssh

HOST_KEY_ALGORITHM = "ssh-ed25519"


def load_host_key(path: Path) -> asyncssh.SSHKey:
    """The daemon's SSH host key, minted on first use and kept.

    A fresh key per start would make every client's known_hosts entry
    look like a man-in-the-middle, so the first start writes one with
    owner-only permissions and every later start reads it back. Two
    daemons racing to mint it both end up reading the one that won.

    Args:
        path (Path): where the private key lives.

    Returns:
        asyncssh.SSHKey: the host key.
    """
    if path.exists():
        return asyncssh.read_private_key(str(path))
    key = asyncssh.generate_private_key(HOST_KEY_ALGORITHM)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return asyncssh.read_private_key(str(path))
    with os.fdopen(fd, "wb") as f:
        f.write(key.export_private_key())
    return key
