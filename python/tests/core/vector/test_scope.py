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

import pytest

from mirage.core.hierarchy.codec import PATH_SAFE, Codec
from mirage.core.hierarchy.scope import INVALID, ROOT, make_detect_scope
from mirage.core.vector.scope import (
    blob_leaf,
    filters_of,
    row_scopes,
    table_of,
)
from mirage.types import ContentType, PathSpec

GROUP_BY = ["label", "kind"]
LEAVES = [
    ("row_text", Codec(suffix=".txt"), ContentType.TEXT),
    blob_leaf("png"),
]


def _match(pinned: str | None, groups: int, path: str):
    detect = make_detect_scope(
        row_scopes(pinned is not None, [PATH_SAFE] * groups, LEAVES)
    )
    return detect(
        PathSpec(virtual=path, directory=path, vfs_path=path.strip("/"))
    )


@pytest.mark.parametrize(
    "pinned,groups,path,kind,table,filters",
    [
        (None, 2, "/", ROOT, None, {}),
        (None, 2, "/animals", "group", "animals", {}),
        (None, 2, "/animals/cat", "group", "animals", {"label": "cat"}),
        (
            None,
            2,
            "/animals/cat/big",
            "group",
            "animals",
            {"label": "cat", "kind": "big"},
        ),
        (
            None,
            2,
            "/animals/cat/big/3.txt",
            "row_text",
            "animals",
            {"label": "cat", "kind": "big"},
        ),
        (
            None,
            2,
            "/animals/cat/big/3.png",
            "row_blob",
            "animals",
            {"label": "cat", "kind": "big"},
        ),
        (None, 2, "/animals/cat/big/3.txt/extra", INVALID, None, {}),
        (
            "animals",
            2,
            "/cat/big",
            "group",
            "animals",
            {"label": "cat", "kind": "big"},
        ),
        ("animals", 0, "/", ROOT, None, {}),
        ("animals", 0, "/3.txt", "row_text", "animals", {}),
        ("animals", 0, "/whatever", INVALID, None, {}),
    ],
)
def test_row_scopes_classify(pinned, groups, path, kind, table, filters):
    match = _match(pinned, groups, path)
    assert match.kind == kind
    if table is not None:
        assert table_of(pinned, match) == table
    assert filters_of(GROUP_BY, match) == filters


@pytest.mark.parametrize(
    "segment,value",
    [
        ("a∕b", "a/b"),
        ("a⁄∕b", "a∕b"),
        ("⁄", ""),
        ("⁄.env", ".env"),
    ],
)
def test_filters_decode_escaped_group_segments(segment, value):
    match = _match("animals", 1, f"/{segment}")
    assert filters_of(["label"], match) == {"label": value}


def test_blob_leaf_takes_the_extension_type():
    match = _match("animals", 0, "/3.png")
    assert match.slots["row_id"] == "3"
    assert match.scope is not None
    assert match.scope.filetype == ContentType.IMAGE_PNG
