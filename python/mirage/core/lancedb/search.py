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

from mirage.accessor.lancedb import LanceDBAccessor
from mirage.cache.index import NULL_INDEX, IndexCacheStore
from mirage.core.hierarchy.codec import PATH_SAFE
from mirage.core.lancedb.query import search_rows
from mirage.core.lancedb.render import render_card
from mirage.types import PathSpec
from mirage.utils.key_prefix import mount_prefix_of
from mirage.vfs.lancedb.config import LanceDBConfig
from mirage.vfs.search import (float_option, int_option, text_option,
                               validate_options)
from mirage.vfs.types import SearchQuery


def _target_table(paths: list[PathSpec], config: LanceDBConfig) -> str | None:
    if config.table:
        return config.table
    for path in paths:
        raw = path.mount_path if isinstance(path, PathSpec) else path
        key = raw.strip("/")
        if key:
            return key.split("/")[0]
    return None


def _canonical_path(row: dict[str, Any], config: LanceDBConfig, table: str,
                    mount_prefix: str) -> str:
    segs: list[str] = []
    if not config.table:
        segs.append(str(table))
    for column in config.group_by:
        if column in row and row[column] is not None:
            segs.append(PATH_SAFE.encode(str(row[column])))
    segs.append(f"{row[config.id_column]}.md")
    prefix = mount_prefix.rstrip("/")
    return prefix + "/" + "/".join(segs)


def _block(row: dict[str, Any], config: LanceDBConfig, table: str,
           mount_prefix: str) -> str:
    path = _canonical_path(row, config, table, mount_prefix)
    distance = row.get("_distance")
    header = path if distance is None else f"{path}:{float(distance):.4f}"
    body_row = {k: v for k, v in row.items() if k != "_distance"}
    content = render_card(body_row, config).decode().rstrip("\n")
    return f"{header}\n{content}"


async def search_rows_output(
    accessor: LanceDBAccessor,
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
        distance = row.get("_distance")
        if threshold > 0 and distance is not None and float(
                distance) > threshold:
            continue
        blocks.append(_block(row, accessor.config, table, mount_prefix))
    if not blocks:
        return b""
    return ("\n".join(blocks) + "\n").encode()


async def search_many(accessor: LanceDBAccessor,
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


async def search_resource(accessor: LanceDBAccessor,
                          path: PathSpec,
                          query: SearchQuery,
                          index: IndexCacheStore = NULL_INDEX) -> list[str]:
    return await search_many(accessor, [path], query, index)
