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

from typing import Any

from mirage.core.airtable.constants import VIEW_SUFFIX
from mirage.utils.naming import make_id_name


def _label(entity: dict[str, Any]) -> str:
    name = entity.get("name")
    return name if isinstance(name, str) and name else str(entity["id"])


def base_dirname(base: dict[str, Any]) -> str:
    """``<Base_Name>__app...``, the one spelling of a base directory.

    Args:
        base (dict[str, Any]): a base-listing row.
    """
    return make_id_name(_label(base), base["id"])


def table_dirname(table: dict[str, Any]) -> str:
    """``<Table_Name>__tbl...``, the one spelling of a table directory.

    Args:
        table (dict[str, Any]): a schema table.
    """
    return make_id_name(_label(table), table["id"])


def view_filename(view: dict[str, Any]) -> str:
    """``<View_Name>__viw....jsonl``, the one spelling of a view file.

    Args:
        view (dict[str, Any]): a schema view.
    """
    return make_id_name(_label(view), view["id"], suffix=VIEW_SUFFIX)
