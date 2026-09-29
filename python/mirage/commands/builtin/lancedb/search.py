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

from dataclasses import replace

from mirage.accessor.lancedb import LanceDBAccessor
from mirage.commands.builtin.lancedb._provision import metadata_provision
from mirage.commands.builtin.lancedb.io import IO
from mirage.commands.builtin.utils.paths import default_paths
from mirage.commands.config import CommandOpts
from mirage.commands.registry import command
from mirage.commands.spec import SPECS
from mirage.commands.spec.flag_view import FlagView
from mirage.io.types import ByteSource, IOResult
from mirage.provision.types import ProvisionResult
from mirage.types import PathSpec
from mirage.vfs.search import search_resources
from mirage.vfs.types import SearchQuery


async def search_provision(accessor: LanceDBAccessor, paths: list[PathSpec],
                           texts: list[str],
                           opts: CommandOpts) -> ProvisionResult:
    return await metadata_provision(
        accessor, paths, texts,
        replace(opts, command="search " + " ".join(texts)))


@command("search",
         vfs="lancedb",
         spec=SPECS["search"],
         provision=search_provision)
async def search(
    accessor: LanceDBAccessor,
    paths: list[PathSpec],
    texts: list[str],
    opts: CommandOpts,
) -> tuple[ByteSource | None, IOResult]:
    fl = FlagView(opts.flags, spec=SPECS["search"])
    if not texts:
        raise ValueError("search: query is required")
    if (fl.as_str("method") or "semantic") != "semantic":
        raise ValueError("search: only the 'semantic' method is supported")
    query = texts[0]
    top_k = fl.as_int("top_k")
    target_paths = default_paths(paths, opts.cwd)
    output = await search_resources(
        IO.search, accessor, target_paths,
        SearchQuery(
            query,
            options={
                "top_k":
                top_k if top_k is not None else accessor.config.search_limit,
                "method": fl.as_str("method") or "semantic",
                "threshold": fl.as_float("threshold") or 0.0
            }), opts.index)
    return output, IOResult()
