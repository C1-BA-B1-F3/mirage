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

from mirage.accessor.lancedb import LanceDBAccessor
from mirage.core.hierarchy.codec import PATH_SAFE
from mirage.core.lancedb.render import render_card
from mirage.core.vector.types import Row


def hit(accessor: LanceDBAccessor, row: Row) -> tuple[list[str], bytes]:
    """A ranked row's path below its table, and its card.

    Args:
        accessor (LanceDBAccessor): the mount's accessor.
        row (Row): the ranked row.
    """
    config = accessor.config
    segments = [
        PATH_SAFE.encode(str(row[column])) for column in config.group_by
        if row.get(column) is not None
    ]
    return segments + [f"{row[config.id_column]}.md"], render_card(row, config)
