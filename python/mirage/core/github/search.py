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

import logging
from dataclasses import dataclass

from mirage.accessor.github import GitHubAccessor
from mirage.core.api.client import SessionArg
from mirage.core.github.client import github_get, github_request_response
from mirage.core.github.config import GhConfig, GitHubConfig
from mirage.core.github.constants import SEARCH_PAGE_SIZE
from mirage.core.github.pushdown import scope_relative_key, unsearchable_keys
from mirage.types import JsonValue, PathSpec
from mirage.utils.key_prefix import mount_key, mount_prefix_of

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    path: str
    sha: str


async def search_code(
    config: GitHubConfig,
    owner: str,
    repo: str,
    query: str,
    path_filter: str | None = None,
    session: SessionArg = None,
) -> tuple[list[SearchResult], bool]:
    """Search one repository's code for a literal, and say if that is all.

    The literal is sent verbatim, so the answer has to vouch for itself: an
    item is kept only when its ``repository.full_name`` names this
    repository (compared case-insensitively, as GitHub resolves ``repo:``),
    and the answer is complete only when ``incomplete_results`` is false and
    ``total_count`` is an integer no larger than the rows returned. A
    missing or malformed field counts against it, which costs a full scan and
    never a missed file.

    Args:
        config (GitHubConfig): GitHub API config.
        owner (str): Repository owner.
        repo (str): Repository name.
        query (str): Literal search pattern.
        path_filter (str | None): Repo-relative directory to search under.
        session (SessionArg): the mount's session pool.

    Returns:
        tuple[list[SearchResult], bool]: this repository's hits, and whether
            the answer was truncated (fewer rows than the search matched).
    """
    q = f"{query} repo:{owner}/{repo}"
    if path_filter:
        q += f" path:{path_filter}"
    data = await github_get(config.token,
                            "/search/code",
                            params={
                                "q": q,
                                "per_page": str(SEARCH_PAGE_SIZE)
                            },
                            base_url=config.base_url,
                            session=session)
    items = data.get("items") or []
    total = data.get("total_count")
    complete = (data.get("incomplete_results") is False
                and isinstance(total, int) and not isinstance(total, bool)
                and total <= len(items))
    want = f"{owner}/{repo}".lower()
    results = []
    for item in items:
        name = (item.get("repository") or {}).get("full_name")
        if isinstance(name, str) and name.lower() == want:
            results.append(SearchResult(path=item["path"], sha=item["sha"]))
    return results, not complete


async def narrow_paths(
    accessor: GitHubAccessor,
    query: str,
    paths: list[PathSpec],
) -> list[PathSpec] | None:
    """Use GitHub code search to narrow grep/rg scopes to candidate files.

    Returns None whenever the narrowed set cannot be trusted as a superset
    of what a full scan would read (a search failure, or an answer that is
    not the whole set), so the caller falls back to the full scan. A trusted
    set also carries every file code search never indexes, which no answer
    can name; those come from the accessor's tree.

    Args:
        accessor (GitHubAccessor): backend handle: the repository, its
            recursive tree, and the session pool each search rides so it
            reuses the mount's connections instead of opening a session.
        query (str): literal search query.
        paths (list[PathSpec]): scope paths, possibly mount-prefixed.

    Returns:
        list[PathSpec] | None: one PathSpec per candidate file under the
            scopes, repo-relative with a leading slash and the original
            mount prefix, or None when narrowing is unusable.
    """
    if not paths:
        return []
    mount_prefix = mount_prefix_of(paths[0].virtual, paths[0].vfs_path)
    narrowed: list[str] = []
    for p in paths:
        key = scope_relative_key(p)
        path_filter = key.strip("/")
        try:
            results, truncated = await search_code(
                accessor.config,
                accessor.owner,
                accessor.repo,
                query=query,
                path_filter=path_filter or None,
                session=accessor.pool,
            )
        except Exception as exc:
            logger.warning(
                "github code search failed (%s); "
                "falling back to per-file scan", exc)
            return None
        if truncated:
            return None
        scope_prefix = path_filter + "/" if path_filter else ""
        hits = [
            r.path for r in results
            if r.path == path_filter or r.path.startswith(scope_prefix)
        ]
        seen = set(hits)
        narrowed.extend(hits)
        narrowed.extend(k for k in unsearchable_keys(accessor.tree, key)
                        if k not in seen)
    out: list[PathSpec] = []
    for n in narrowed:
        virtual = mount_prefix + "/" + n.lstrip("/")
        out.append(
            PathSpec(virtual=virtual,
                     directory="",
                     vfs_path=mount_key(virtual, mount_prefix),
                     resolved=True))
    return out


async def search(config: GhConfig,
                 kind: str,
                 query: str,
                 limit: int,
                 sort: str | None = None,
                 order: str | None = None) -> list[JsonValue]:
    """Fetch a bounded REST search, following the server's pagination.

    Args:
        config (GhConfig): account connection.
        kind (str): REST search resource.
        query (str): GitHub search expression.
        limit (int): maximum rows.
        sort (str | None): server ordering field.
        order (str | None): ordering direction.
    """
    params = {"q": query, "per_page": str(min(limit, 100)), "page": "1"}
    if sort is not None:
        params["sort"] = sort
    if order is not None:
        params["order"] = order
    rows: list[JsonValue] = []
    page = 1
    while len(rows) < limit:
        params["page"] = str(page)
        response = await github_request_response(
            config.token,
            "GET",
            f"/search/{kind}",
            params=params,
            base_url=config.base_url,
            headers={
                "Accept":
                "application/vnd.github.text-match+json"
                if kind == "code" else "application/vnd.github.v3+json"
            })
        body = response.data
        items = body.get("items", []) if isinstance(body, dict) else []
        if not isinstance(items, list):
            raise ValueError("invalid search response: items must be an array")
        rows.extend(items[:limit - len(rows)])
        if not items or 'rel="next"' not in response.headers.get("link", ""):
            break
        page += 1
    return rows
