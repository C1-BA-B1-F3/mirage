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

from typing import TYPE_CHECKING

from mirage.vfs.mem0.config import Mem0Config

if TYPE_CHECKING:
    from mirage.vfs.mem0.mem0 import Mem0VFS

__all__ = ["Mem0Config", "Mem0VFS"]


def __getattr__(name: str) -> "type[Mem0VFS]":
    if name == "Mem0VFS":
        from mirage.vfs.mem0.mem0 import Mem0VFS

        return Mem0VFS
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
