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

from mirage.core.hierarchy.scope import INVALID, make_detect_scope
from mirage.core.lancedb.scope import scopes_for
from mirage.core.vector.scope import filters_of
from mirage.types import PathSpec
from mirage.vfs.lancedb.config import LanceDBConfig


def _cfg(**kw) -> LanceDBConfig:
    base = dict(
        uri="/tmp/db",
        group_by=["label", "kind"],
        id_column="id",
        title_column="name",
        blob_column="image_bytes",
        blob_ext="png",
        vector_column="vector",
    )
    base.update(kw)
    return LanceDBConfig(**base)


def _ps(path: str) -> PathSpec:
    return PathSpec(virtual=path, directory=path, vfs_path=path.strip("/"))


def _detect(config: LanceDBConfig):
    return make_detect_scope(scopes_for(config))


def test_row_card():
    config = _cfg()
    match = _detect(config)(_ps("/animals/cat/big/3.md"))
    assert match.kind == "row_card"
    assert match.slots["row_id"] == "3"
    assert filters_of(config.group_by, match) == {
        "label": "cat",
        "kind": "big",
    }


def test_row_blob():
    match = _detect(_cfg())(_ps("/animals/cat/big/3.png"))
    assert match.kind == "row_blob"
    assert match.slots["row_id"] == "3"


def test_blob_needs_blob_column():
    match = _detect(_cfg(blob_column=None))(_ps("/animals/cat/big/3.png"))
    assert match.kind == INVALID
