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

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mirage.vfs.base import BaseVFS
    from mirage.vfs.disk import DiskVFS
    from mirage.vfs.ram import RAMVFS
    from mirage.vfs.redis import RedisVFS

_EXPORTS: dict[str, tuple[str, ...]] = {
    "mirage.vfs.base": ("BaseVFS",),
    "mirage.vfs.disk": ("DiskVFS",),
    "mirage.vfs.ram": ("RAMVFS",),
    "mirage.vfs.redis": ("RedisVFS",),
}
_MODULE_OF = {
    name: module for module, names in _EXPORTS.items() for name in names
}

__all__ = [
    "BaseVFS",
    "DiskVFS",
    "RAMVFS",
    "RedisVFS",
]


def __getattr__(name: str) -> Any:
    module = _MODULE_OF.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(module), name)
    globals()[name] = value
    return value
