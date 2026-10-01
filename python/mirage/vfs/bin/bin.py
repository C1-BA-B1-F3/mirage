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

from collections.abc import Callable

from mirage.accessor.bin import BinAccessor
from mirage.commands.builtin.bin import COMMANDS
from mirage.commands.config import RegisteredCommand, registered_commands
from mirage.ops.bin import OPS
from mirage.ops.registry import RegisteredOp
from mirage.vfs.base import BaseVFS


class BinViewVFS(BaseVFS):
    """Read-only view VFS backing the /usr/bin mount.

    Lists one executable file per program the session can run, rendered
    from the workspace's command lookup on every call; holds no storage
    of its own.

    Args:
        programs (Callable[[], list[str]]): every program name the
            session can run, sorted.
        note (Callable[[str], str | None]): the line one program's file
            says about it, None when the name runs as no program.
    """

    accessor: BinAccessor
    name = "bin"
    # A stub's size is its rendering: cheap, no network, never None.
    sizes_always_known: bool = True

    def __init__(self, programs: Callable[[], list[str]],
                 note: Callable[[str], str | None]) -> None:
        super().__init__()
        self.accessor = BinAccessor(programs, note)

    def ops(self) -> list[RegisteredOp]:
        return OPS

    def commands(self) -> list[RegisteredCommand]:
        return registered_commands(COMMANDS)
