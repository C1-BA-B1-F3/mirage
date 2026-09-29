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

from typing import Any, cast

from mirage.core.github.client import github_request
from mirage.core.github.config import GhConfig
from mirage.core.github.paginate import github_pages
from mirage.core.github.repo import RepoRef
from mirage.types import JsonValue


def _path(ref: RepoRef, tail: str = "") -> str:
    return f"/repos/{ref.owner}/{ref.repo}/issues{tail}"


def _only_issue(value: JsonValue, number: int) -> JsonValue:
    if isinstance(value, dict) and "pull_request" in value:
        raise ValueError(f"#{number} is a pull request, not an issue")
    return value


async def list_issues(config: GhConfig, ref: RepoRef, params: dict[str, str],
                      limit: int) -> list[dict[str, Any]]:
    return await github_pages(config,
                              _path(ref),
                              params=params,
                              limit=limit,
                              include=lambda row: "pull_request" not in row)


async def get_issue(config: GhConfig, ref: RepoRef, number: int) -> JsonValue:
    value = await github_request(config.token,
                                 "GET",
                                 _path(ref, f"/{number}"),
                                 base_url=config.base_url)
    return _only_issue(value, number)


async def create_issue(config: GhConfig, ref: RepoRef,
                       body: dict[str, JsonValue]) -> JsonValue:
    return await github_request(config.token,
                                "POST",
                                _path(ref),
                                body,
                                base_url=config.base_url)


async def edit_issue(config: GhConfig, ref: RepoRef, number: int,
                     body: dict[str, JsonValue]) -> JsonValue:
    await get_issue(config, ref, number)
    return await github_request(config.token,
                                "PATCH",
                                _path(ref, f"/{number}"),
                                body,
                                base_url=config.base_url)


async def comment_issue(config: GhConfig, ref: RepoRef, number: int,
                        body: str) -> JsonValue:
    await get_issue(config, ref, number)
    return await github_request(config.token,
                                "POST",
                                _path(ref, f"/{number}/comments"),
                                {"body": body},
                                base_url=config.base_url)


COMMENTS_QUERY = """
query($owner: String!, $repo: String!, $number: Int!, $cursor: String) {
  repository(owner: $owner, name: $repo) {
    issueOrPullRequest(number: $number) {
      ... on Issue {
        comments(first: 100, after: $cursor) {
          nodes { ...CommentFields }
          pageInfo { hasNextPage endCursor }
        }
      }
      ... on PullRequest {
        comments(first: 100, after: $cursor) {
          nodes { ...CommentFields }
          pageInfo { hasNextPage endCursor }
        }
      }
    }
  }
}
fragment CommentFields on IssueComment {
  id
  author { login }
  authorAssociation
  body
  createdAt
  includesCreatedEdit
  isMinimized
  minimizedReason
  reactionGroups { content users { totalCount } }
  url
  viewerDidAuthor
}
"""


async def issue_comments(config: GhConfig, ref: RepoRef,
                         number: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        response = await github_request(config.token,
                                        "POST",
                                        "/graphql", {
                                            "query": COMMENTS_QUERY,
                                            "variables": {
                                                "owner": ref.owner,
                                                "repo": ref.repo,
                                                "number": number,
                                                "cursor": cursor
                                            }
                                        },
                                        base_url=config.base_url)
        if not isinstance(response, dict):
            raise ValueError("Invalid GitHub comments response")
        payload = cast(dict[str, Any], response)
        if payload.get("errors"):
            raise ValueError("; ".join(e["message"]
                                       for e in payload["errors"]))
        repo = (payload.get("data") or {}).get("repository") or {}
        comments = (repo.get("issueOrPullRequest") or {}).get("comments")
        if comments is None:
            raise ValueError(
                "Could not resolve comments for this issue or pull request")
        rows.extend(comments["nodes"])
        page = comments["pageInfo"]
        if not page["hasNextPage"]:
            return rows
        next_cursor = page["endCursor"]
        if not next_cursor or next_cursor == cursor:
            raise ValueError("GitHub returned a non-advancing comments cursor")
        cursor = next_cursor
