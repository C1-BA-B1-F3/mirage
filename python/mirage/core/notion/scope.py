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

from mirage.core.hierarchy.scope import Scope, Slot, make_detect_scope
from mirage.types import ContentType

# A page tree nests arbitrarily, so the page level is one VARIADIC slot:
# `pages/a__1/b__2` is a page at any depth, and the slots hold the DEEPEST
# page's label and id, which is the one the path addresses. A database row
# is a page too, but one level of its own: the data source lists its rows
# as `rows.jsonl` rather than as directories, so a row is reached by its
# path alone and proves itself (`row` and `row_json`), while the pages
# under a row are listed by the row as any child page is.
_PAGE = Slot("page", id_key="page_id", variadic=True)
_ROW = Slot("row", id_key="row_id")
_DB = ("databases", Slot("database", id_key="database_id"))
_DS = _DB + (Slot("data_source", id_key="data_source_id"), )

# One description of the tree: readdir, stat and read all classify
# through it, so the file surface cannot disagree with itself about what
# a path means. The `page` and `page_json` kinds are declared twice, once
# per root, because a page behaves identically wherever it hangs.
SCOPES = (
    Scope(kind="pages", segments=("pages", ), probed=False),
    Scope(kind="databases", segments=("databases", ), probed=False),
    Scope(kind="page_json",
          segments=("pages", _PAGE, "page.json"),
          leaf=True,
          filetype=ContentType.JSON),
    Scope(kind="page", segments=("pages", _PAGE)),
    Scope(kind="database_json",
          segments=_DB + ("database.json", ),
          leaf=True,
          filetype=ContentType.JSON),
    Scope(kind="database", segments=_DB),
    Scope(kind="data_source_json",
          segments=_DS + ("data_source.json", ),
          leaf=True,
          filetype=ContentType.JSON),
    Scope(kind="rows_jsonl",
          segments=_DS + ("rows.jsonl", ),
          leaf=True,
          filetype=ContentType.TEXT),
    Scope(kind="data_source", segments=_DS),
    Scope(kind="row_json",
          segments=_DS + (_ROW, "page.json"),
          leaf=True,
          filetype=ContentType.JSON),
    Scope(kind="row", segments=_DS + (_ROW, )),
    Scope(kind="page_json",
          segments=_DS + (_ROW, _PAGE, "page.json"),
          leaf=True,
          filetype=ContentType.JSON),
    Scope(kind="page", segments=_DS + (_ROW, _PAGE)),
)

detect_scope = make_detect_scope(SCOPES)
