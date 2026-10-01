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

import asyncssh

from mirage.accessor.base import Accessor
from mirage.core.ssh.client import _connect_kwargs
from mirage.core.ssh.config import SSHConfig


class SSHAccessor(Accessor):
    def __init__(self, config: SSHConfig) -> None:
        self.config = config
        self._lock = asyncio.Lock()
        self._conn: asyncssh.SSHClientConnection | None = None
        self._sftp: asyncssh.SFTPClient | None = None

    @property
    def root(self) -> str:
        return self.config.root

    async def sftp(self) -> asyncssh.SFTPClient:
        async with self._lock:
            if self._sftp is None:
                conn = await asyncssh.connect(**_connect_kwargs(self.config))
                try:
                    self._sftp = await conn.start_sftp_client()
                except BaseException:
                    conn.close()
                    await conn.wait_closed()
                    raise
                self._conn = conn
            return self._sftp

    async def close(self) -> None:
        async with self._lock:
            if self._conn is not None:
                self._conn.close()
                await self._conn.wait_closed()
                self._conn = None
                self._sftp = None
