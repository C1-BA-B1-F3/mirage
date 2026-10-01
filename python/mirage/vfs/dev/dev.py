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

from mirage.accessor.ram import RAMAccessor
from mirage.commands.builtin.dev import COMMANDS
from mirage.commands.config import RegisteredCommand, registered_commands
from mirage.ops.dev import OPS as DEV_OPS
from mirage.ops.registry import RegisteredOp
from mirage.types import VFSName
from mirage.vfs.base import BaseVFS
from mirage.vfs.dev.store import DevStore


class DevVFS(BaseVFS):
    accessor: RAMAccessor
    name: str = VFSName.RAM
    # Device metadata is synthetic and needs no content fetch.
    sizes_always_known: bool = True

    def __init__(self) -> None:
        super().__init__()
        self._store = DevStore()
        self.accessor = RAMAccessor(self._store)

    def ops(self) -> list[RegisteredOp]:
        return DEV_OPS

    def commands(self) -> list[RegisteredCommand]:
        return registered_commands(COMMANDS)

    def allocate_input(self) -> tuple[str, int]:
        return self._store.files.allocate_input()

    def set_input(self, path: str, allocation: int, data: bytes) -> None:
        self._store.files.set_input(path, allocation, data)

    def release_input(self, path: str, allocation: int) -> None:
        if self._store.files.release_input(path, allocation):
            self._store.modified.pop(path[4:], None)
            self._store.attrs.pop(path[4:], None)
