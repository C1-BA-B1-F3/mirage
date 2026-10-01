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

from collections.abc import Sequence

from mirage.core.hierarchy.codec import Codec
from mirage.core.hierarchy.scope import Scope, ScopeMatch, Segment, Slot
from mirage.core.vector.types import Leaf
from mirage.utils.filetype import content_type_for_extension


def blob_leaf(ext: str) -> Leaf:
    """The leaf a blob column renders as, one file per row.

    Args:
        ext (str): the configured blob extension.
    """
    return (
        "row_blob",
        Codec(suffix="." + ext),
        content_type_for_extension(ext),
    )


def row_scopes(
    pinned: bool, groups: Sequence[Codec], leaves: Sequence[Leaf]
) -> tuple[Scope, ...]:
    """A mount's scope table, shaped by its config.

    The tree is a function of the mount config, not of the backend: a
    pinned table removes the leading table segment, every ``group_by``
    column adds one directory level, and each leaf adds one file per
    row. Group slots are named positionally (``g0``, ``g1``, ...) so a
    column named ``table`` cannot collide with the table slot;
    ``filters_of`` maps them back to column names. Every partial depth
    shares the one ``group`` kind, and its lister derives the depth from
    the slots, so the lister table stays static while the scope table
    varies per mount.

    Args:
        pinned (bool): whether the config pins one table.
        groups (Sequence[Codec]): each group level's segment codec.
        leaves (Sequence[Leaf]): each leaf's kind, suffix codec and
            content type.
    """
    prefix: tuple[Segment, ...] = () if pinned else (Slot("table"),)
    slots = tuple(Slot(f"g{i}", codec) for i, codec in enumerate(groups))
    scopes = [
        Scope(kind="group", segments=prefix + slots[:depth])
        for depth in range(len(slots) + 1)
        if depth or prefix
    ]
    scopes.extend(
        Scope(
            kind=kind,
            segments=prefix + slots + (Slot("row_id", codec),),
            leaf=True,
            filetype=filetype,
        )
        for kind, codec, filetype in leaves
    )
    return tuple(scopes)


def table_of(pinned: str | None, match: ScopeMatch) -> str:
    """The table a match addresses: pinned, or the path's first slot.

    Args:
        pinned (str | None): the table the config pins.
        match (ScopeMatch): a match from the mount's classifier.
    """
    return pinned or match.slots["table"]


def filters_of(group_by: Sequence[str], match: ScopeMatch) -> dict[str, str]:
    """The match's group filters, keyed back to column names.

    Args:
        group_by (Sequence[str]): the configured group columns.
        match (ScopeMatch): a match from the mount's classifier.
    """
    filters: dict[str, str] = {}
    for i, column in enumerate(group_by):
        value = match.slots.get(f"g{i}")
        if value is None:
            break
        filters[column] = value
    return filters
