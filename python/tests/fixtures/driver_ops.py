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

from weakref import WeakKeyDictionary

from mirage.vfs.base import BaseVFS
from mirage.vfs.testing import DriverOps

_TABLES: WeakKeyDictionary[BaseVFS, DriverOps] = WeakKeyDictionary()


def ops(vfs: BaseVFS) -> DriverOps:
    """The op table of ``vfs``, bound once per instance so its index store
    persists across calls.

    Args:
        vfs (BaseVFS): the driver under test.
    """
    table = _TABLES.get(vfs)
    if table is None:
        table = DriverOps(vfs)
        _TABLES[vfs] = table
    return table
