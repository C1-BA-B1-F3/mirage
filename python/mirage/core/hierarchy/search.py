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

import re
from collections.abc import Awaitable, Callable, Mapping

from mirage.cache.index import NULL_INDEX, IndexCacheStore
from mirage.commands.builtin.grep_pattern import compile_pattern
from mirage.commands.builtin.grep_pushdown import grep_search_options
from mirage.core.hierarchy.probe import A
from mirage.core.hierarchy.scope import ROOT, DetectFn, ScopeMatch
from mirage.types import PathSpec
from mirage.vfs.types import SearchOp, SearchQuery, StatOp


def query_matcher(query: SearchQuery) -> re.Pattern[str]:
    """The matcher the generic scan would compile for this request.

    A searcher that has to decide a line itself (a candidate the service
    returned, or a line it rendered) decides it with this, so what it
    prints is what grep over the same file would print.

    Args:
        query (SearchQuery): the qualified request.
    """
    options = grep_search_options(query)
    return compile_pattern(query.query,
                           ignore_case=options.ignore_case,
                           fixed_string=options.fixed_string,
                           whole_word=options.whole_word,
                           basic=options.basic)


Searcher = Callable[[A, ScopeMatch, SearchQuery], Awaitable[list[str]]]


def make_search_op(detect: DetectFn,
                   searchers: Mapping[str, Searcher[A]],
                   stat: StatOp | None = None) -> SearchOp:
    """Adapt scope-specific search functions to the VFS search contract.

    Args:
        detect (DetectFn): classify the requested path.
        searchers (Mapping[str, Searcher]): supported scope handlers.
        stat (StatOp | None): optional existence check for non-root scopes.
    """

    async def search(accessor: A,
                     path: PathSpec,
                     query: SearchQuery,
                     index: IndexCacheStore = NULL_INDEX) -> list[str] | None:
        match = detect(path)
        searcher = searchers.get(match.kind)
        if searcher is None:
            return None
        if stat is not None and match.kind != ROOT:
            await stat(accessor, path, index)
        return await searcher(accessor, match, query)

    return search
