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

from mirage.utils.naming import fit_id_name, parse_id_name
from mirage.utils.sanitize import sanitize_name

split_suffix_id = parse_id_name


def format_segment(title: str, object_id: str) -> str:
    """Join a Notion object's title to its id inside the NAME_MAX budget.

    The one place the pair is composed, mirroring the TypeScript
    ``formatSegment``. Every dirname below and the child-page rows in
    ``readdir`` route through it so a title long enough to be trimmed is
    trimmed the same way everywhere -- a second spelling names a path that
    does not exist.

    Args:
        title (str): raw title, empty for an untitled object.
        object_id (str): Notion object id, never trimmed.

    Returns:
        str: dirname of shape ``<label>__<id>``.
    """
    return fit_id_name(
        sanitize_name(title) if title else "untitled", object_id
    )


def page_dirname(page: dict[str, Any]) -> str:
    return format_segment(extract_title(page), page["id"])


def database_dirname(database: dict[str, Any]) -> str:
    return format_segment(extract_database_title(database), database["id"])


def data_source_dirname(data_source: dict[str, Any]) -> str:
    return format_segment(
        extract_data_source_title(data_source), data_source["id"]
    )


def extract_data_source_title(data_source: dict[str, Any]) -> str:
    """Read a data source's label from either shape it arrives in.

    The data source object carries rich-text ``title``; the stubs listed
    under a database's ``data_sources`` carry a plain ``name``. Both name
    the same thing, so both must render the same directory.

    Args:
        data_source (dict[str, Any]): a data source object or stub.

    Returns:
        str: the plain-text label, empty when neither field is present.
    """
    name = data_source.get("name")
    if isinstance(name, str):
        return name
    return extract_database_title(data_source)


def extract_title(page: dict[str, Any]) -> str:
    props = page.get("properties", {})
    if not isinstance(props, dict):
        return ""
    for prop in props.values():
        if not isinstance(prop, dict):
            continue
        if prop.get("type") == "title":
            title_items = prop.get("title", [])
            return "".join(item.get("plain_text", "") for item in title_items)
    return ""


def extract_database_title(database: dict[str, Any]) -> str:
    title_items = database.get("title", [])
    return "".join(item.get("plain_text", "") for item in title_items)
