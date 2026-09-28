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

from mirage.accessor.gsheets import GSheetsAccessor
from mirage.commands.builtin.gsheets import COMMANDS
from mirage.commands.builtin.gsheets.io import IO
from mirage.core.google.client import TokenManager
from mirage.ops.gsheets import OPS as GSHEETS_VFS_OPS
from mirage.types import VFSName
from mirage.vfs.bound import BoundVFS
from mirage.vfs.gsheets.config import GSheetsConfig
from mirage.vfs.gsheets.prompt import PROMPT, WRITE_PROMPT


class GSheetsVFS(BoundVFS):

    accessor: GSheetsAccessor
    name: str = VFSName.GSHEETS
    caches_reads: bool = True
    # An API-backed tree that changes rarely; a day-long index spares the
    # provider a full re-walk every 10 minutes. Mirrors the TypeScript
    # VFS.
    index_ttl: float = 86_400
    # Reads stamp listing metadata; a fresh stat checks Drive by file ID.
    READ_REVALIDATABLE: bool = True
    PROMPT: str = PROMPT
    WRITE_PROMPT: str = WRITE_PROMPT

    def __init__(self, config: GSheetsConfig) -> None:
        super().__init__(io=IO)
        self.config = config
        self._token_manager = TokenManager(config)
        self.accessor = GSheetsAccessor(self.config, self._token_manager)
        for fn in COMMANDS:
            self.register(fn)
        for fn in GSHEETS_VFS_OPS:
            self.register_op(fn)

    async def close(self) -> None:
        """Drain the token manager's connection pool with the VFS."""
        await self._token_manager.close()
        await super().close()

    def get_state(self) -> dict[str, Any]:
        return self.config_state(self.config)
