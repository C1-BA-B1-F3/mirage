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

from mirage.core.hierarchy.codec import JSONL_NAME
from mirage.core.hierarchy.scope import Scope, Slot, make_detect_scope
from mirage.types import ContentType

_BASE = ("bases", Slot("base", id_key="base_id"))
_TABLE = _BASE + (Slot("table", id_key="table_id"), )

# One description of the tree for readdir, stat and read. A base holds
# only tables, so a table directory sits right under its base beside
# base.json; the literal leaves are declared before the table slot, and a
# table's `label__tbl...` name can never spell one of them anyway.
SCOPES = (
    Scope(kind="bases", segments=("bases", ), probed=False),
    Scope(kind="base", segments=_BASE),
    Scope(kind="base_json",
          segments=_BASE + ("base.json", ),
          leaf=True,
          filetype=ContentType.JSON),
    Scope(kind="table", segments=_TABLE),
    Scope(kind="table_json",
          segments=_TABLE + ("table.json", ),
          leaf=True,
          filetype=ContentType.JSON),
    Scope(kind="records",
          segments=_TABLE + ("records.jsonl", ),
          leaf=True,
          filetype=ContentType.TEXT),
    Scope(kind="views", segments=_TABLE + ("views", )),
    Scope(kind="view",
          segments=_TABLE +
          ("views", Slot("view", JSONL_NAME, id_key="view_id")),
          leaf=True,
          filetype=ContentType.TEXT),
)

detect_scope = make_detect_scope(SCOPES)
