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

from mirage.accessor.qdrant import QdrantAccessor
from mirage.core.qdrant.naming import group_name, row_stem
from mirage.core.qdrant.payload import field_value
from mirage.core.qdrant.render import render_json, render_text
from mirage.core.vector.types import Row


def hit(accessor: QdrantAccessor, row: Row) -> tuple[list[str], bytes]:
    """A ranked point's path below its collection, and its body.

    The source text when the point has one, its ``.json`` otherwise.

    Args:
        accessor (QdrantAccessor): the mount's accessor.
        row (Row): the ranked point.
    """
    config = accessor.config
    segments = [
        group_name(value, basename=column in config.basename_fields)
        for column in config.group_by
        if (value := field_value(row, column)) is not None
    ]
    stem = row_stem(row, config)
    if config.text_field and field_value(row, config.text_field) is not None:
        return segments + [f"{stem}.txt"], render_text(row, config)
    return segments + [f"{stem}.json"], render_json(row, config)
