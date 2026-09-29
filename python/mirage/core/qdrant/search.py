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

from mirage.accessor.qdrant import QdrantAccessor
from mirage.cache.index import NULL_INDEX, IndexCacheStore
from mirage.core.qdrant.naming import group_name, row_stem
from mirage.core.qdrant.payload import field_value
from mirage.core.qdrant.query import search_rows
from mirage.core.qdrant.render import render_json, render_text
from mirage.types import PathSpec
from mirage.utils.key_prefix import mount_prefix_of
from mirage.vfs.qdrant.config import QdrantConfig
from mirage.vfs.search import (float_option, int_option, text_option,
                               validate_options)
from mirage.vfs.types import SearchQuery


def _content_ext(row: dict[str, Any], config: QdrantConfig) -> str:
    if config.text_field and field_value(row, config.text_field) is not None:
        return "txt"
    return "json"


def _target_table(paths: list[PathSpec], config: QdrantConfig) -> str | None:
    if config.collection:
        return config.collection
    for path in paths:
        raw = path.mount_path if isinstance(path, PathSpec) else path
        key = raw.strip("/")
        if key:
            return key.split("/")[0]
    return None


def _canonical_path(row: dict[str, Any], config: QdrantConfig, table: str,
                    mount_prefix: str) -> str:
    segs: list[str] = []
    if not config.collection:
        segs.append(str(table))
    for column in config.group_by:
        value = field_value(row, column)
        if value is not None:
            segs.append(
                group_name(value, basename=column in config.basename_fields))
    segs.append(f"{row_stem(row, config)}.{_content_ext(row, config)}")
    prefix = mount_prefix.rstrip("/")
    return prefix + "/" + "/".join(segs)


def _block(row: dict[str, Any], config: QdrantConfig, table: str,
           mount_prefix: str) -> str:
    path = _canonical_path(row, config, table, mount_prefix)
    score = row.get("_score")
    header = path if score is None else f"{path}:{float(score):.4f}"
    body_row = {k: v for k, v in row.items() if k != "_score"}
    if _content_ext(row, config) == "txt":
        content = render_text(body_row, config).decode().rstrip("\n")
    else:
        content = render_json(body_row, config).decode().rstrip("\n")
    return f"{header}\n{content}"


async def search_rows_output(
    accessor: QdrantAccessor,
    query: str,
    paths: list[PathSpec],
    top_k: int,
    threshold: float,
    mount_prefix: str,
) -> bytes:
    if not query:
        raise ValueError("search: query is required")
    if top_k <= 0:
        raise ValueError("search: top-k must be positive")
    table = _target_table(paths, accessor.config)
    if table is None:
        raise FileNotFoundError("search: no table to search")
    rows = await search_rows(accessor, table, query, top_k)
    blocks: list[str] = []
    for row in rows:
        score = row.get("_score")
        if threshold > 0 and score is not None and float(score) < threshold:
            continue
        blocks.append(_block(row, accessor.config, table, mount_prefix))
    if not blocks:
        return b""
    return ("\n".join(blocks) + "\n").encode()


async def search_many(accessor: QdrantAccessor,
                      paths: list[PathSpec],
                      query: SearchQuery,
                      index: IndexCacheStore = NULL_INDEX) -> list[str]:
    validate_options(query, {'top_k', 'method', 'threshold'})
    top_k = int_option(query, "top_k", accessor.config.search_limit)
    if not paths:
        raise ValueError("search: at least one scope is required")
    prefix = mount_prefix_of(paths[0].virtual, paths[0].vfs_path)
    method = text_option(query, "method", "semantic")
    threshold = float_option(query, "threshold", 0.0)
    if method != "semantic":
        raise ValueError("search: only the 'semantic' method is supported")
    output = await search_rows_output(accessor,
                                      query.query,
                                      paths,
                                      top_k=top_k,
                                      threshold=threshold,
                                      mount_prefix=prefix)
    return output.decode().removesuffix("\n").split("\n") if output else []


async def search_resource(accessor: QdrantAccessor,
                          path: PathSpec,
                          query: SearchQuery,
                          index: IndexCacheStore = NULL_INDEX) -> list[str]:
    return await search_many(accessor, [path], query, index)
