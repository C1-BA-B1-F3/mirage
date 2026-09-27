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

from typing import Any

from mirage.accessor.gcal import GCalAccessor
from mirage.commands.builtin.gcal import COMMANDS
from mirage.commands.builtin.gcal.io import IO
from mirage.core.google.client import TokenManager
from mirage.ops.gcal import OPS as GCAL_VFS_OPS
from mirage.types import VFSName
from mirage.vfs.bound import BoundVFS
from mirage.vfs.gcal.config import GCalConfig
from mirage.vfs.gcal.prompt import PROMPT, WRITE_PROMPT


class GCalVFS(BoundVFS):

    accessor: GCalAccessor
    name: str = VFSName.GCAL
    caches_reads: bool = True
    # Shorter than the other Google mounts: a calendar is edited by other
    # people and a day-long index would keep serving a schedule that has
    # already moved.
    index_ttl: float = 300
    PROMPT: str = PROMPT
    WRITE_PROMPT: str = WRITE_PROMPT

    def __init__(self, config: GCalConfig) -> None:
        super().__init__(io=IO)
        self.config = config
        self._token_manager = TokenManager(config)
        self.accessor = GCalAccessor(self.config, self._token_manager)
        self.PROMPT = PROMPT + self.accessor.time_range.prompt()
        for fn in COMMANDS:
            self.register(fn)
        for fn in GCAL_VFS_OPS:
            self.register_op(fn)

    async def close(self) -> None:
        """Drain the token manager's connection pool with the VFS."""
        await self._token_manager.close()
        await super().close()

    def get_state(self) -> dict[str, Any]:
        return self.config_state(self.config)
