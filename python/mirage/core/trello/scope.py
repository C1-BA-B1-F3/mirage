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

from mirage.core.hierarchy.codec import JSON_NAME
from mirage.core.hierarchy.scope import Scope, Slot, make_detect_scope
from mirage.types import ContentType

_WS = ("workspaces", Slot("workspace", id_key="workspace_id"))
_BOARD = _WS + ("boards", Slot("board", id_key="board_id"))
_LIST = _BOARD + ("lists", Slot("list", id_key="list_id"))
_CARD = _LIST + ("cards", Slot("card", id_key="card_id"))

# One description of the tree: readdir, stat and read all classify
# through it, so the file surface cannot disagree with itself about what
# a path means. Every dynamic level is a `label__id` directory whose id
# rides in the slots, which is what lets a reader reach the API without
# resolving the path through the index first.
SCOPES = (
    Scope(kind="workspaces", segments=("workspaces",), probed=False),
    Scope(kind="workspace", segments=_WS),
    Scope(
        kind="workspace_json",
        segments=_WS + ("workspace.json",),
        leaf=True,
        filetype=ContentType.JSON,
    ),
    Scope(kind="boards", segments=_WS + ("boards",)),
    Scope(kind="board", segments=_BOARD),
    Scope(
        kind="board_json",
        segments=_BOARD + ("board.json",),
        leaf=True,
        filetype=ContentType.JSON,
    ),
    Scope(kind="members", segments=_BOARD + ("members",)),
    Scope(
        kind="member",
        segments=_BOARD
        + ("members", Slot("member", JSON_NAME, id_key="member_id")),
        leaf=True,
        filetype=ContentType.JSON,
    ),
    Scope(kind="labels", segments=_BOARD + ("labels",)),
    Scope(
        kind="label",
        segments=_BOARD
        + ("labels", Slot("label", JSON_NAME, id_key="label_id")),
        leaf=True,
        filetype=ContentType.JSON,
    ),
    Scope(kind="lists", segments=_BOARD + ("lists",)),
    Scope(kind="list", segments=_LIST),
    Scope(
        kind="list_json",
        segments=_LIST + ("list.json",),
        leaf=True,
        filetype=ContentType.JSON,
    ),
    Scope(kind="cards", segments=_LIST + ("cards",)),
    Scope(kind="card", segments=_CARD),
    Scope(
        kind="card_json",
        segments=_CARD + ("card.json",),
        leaf=True,
        filetype=ContentType.JSON,
    ),
    Scope(
        kind="comments_jsonl",
        segments=_CARD + ("comments.jsonl",),
        leaf=True,
        filetype=ContentType.TEXT,
    ),
)

detect_scope = make_detect_scope(SCOPES)
