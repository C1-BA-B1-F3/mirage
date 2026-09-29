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

from mirage.core.github.config import GhConfig
from mirage.core.github.issue import (comment_issue, edit_issue, get_issue,
                                      issue_comments, list_issues)
from mirage.core.github.repo import RepoRef


@pytest.mark.asyncio
async def test_list_issues_filters_pull_requests(monkeypatch):
    calls = []

    async def pages(config, path, *, params, limit, include):
        calls.append((path, params, limit, include))
        return [
            row for row in [{
                "number": 1
            }, {
                "number": 2,
                "pull_request": {}
            }] if include(row)
        ]

    monkeypatch.setitem(list_issues.__globals__, "github_pages", pages)
    rows = await list_issues(GhConfig(token="t"), RepoRef("o", "r"),
                             {"state": "all"}, 7)

    assert rows == [{"number": 1}]
    path, params, limit, include = calls[0]
    assert (path, params, limit) == ("/repos/o/r/issues", {"state": "all"}, 7)
    assert include({"number": 1}) is True
    assert include({"pull_request": {}}) is False


@pytest.mark.asyncio
@pytest.mark.parametrize("verb", ["get", "edit", "comment"])
async def test_direct_issue_verbs_reject_pull_request_numbers(
        monkeypatch, verb):
    calls = []

    async def request(token, method, path, *args, base_url=None):
        calls.append((method, path))
        return {"number": 4, "pull_request": {"url": "x"}}

    monkeypatch.setitem(get_issue.__globals__, "github_request", request)
    config = GhConfig(token="t")
    ref = RepoRef("o", "r")

    with pytest.raises(ValueError, match="pull request, not an issue"):
        if verb == "get":
            await get_issue(config, ref, 4)
        elif verb == "edit":
            await edit_issue(config, ref, 4, {"state": "closed"})
        else:
            await comment_issue(config, ref, 4, "no")

    assert calls == [("GET", "/repos/o/r/issues/4")]


@pytest.mark.asyncio
async def test_comments_follow_graphql_cursors(monkeypatch):
    cursors = []

    async def request(token, method, path, body, *, base_url):
        cursor = body["variables"]["cursor"]
        cursors.append(cursor)
        assert (method, path) == ("POST", "/graphql")
        return {
            "data": {
                "repository": {
                    "issueOrPullRequest": {
                        "comments": {
                            "nodes": [{
                                "body":
                                "first" if cursor is None else "second"
                            }],
                            "pageInfo": {
                                "hasNextPage": cursor is None,
                                "endCursor": "next"
                            },
                        }
                    }
                }
            }
        }

    monkeypatch.setitem(issue_comments.__globals__, "github_request", request)
    rows = await issue_comments(GhConfig(token="t"), RepoRef("o", "r"), 1)
    assert rows == [{"body": "first"}, {"body": "second"}]
    assert cursors == [None, "next"]


@pytest.mark.asyncio
async def test_comments_report_graphql_errors(monkeypatch):
    message = "Could not resolve repository"

    async def request(*args, **kwargs):
        assert args[1] == "POST"
        return {"errors": [{"message": message}]}

    monkeypatch.setitem(issue_comments.__globals__, "github_request", request)
    with pytest.raises(ValueError, match="Could not resolve repository"):
        await issue_comments(GhConfig(token="t"), RepoRef("o", "r"), 1)
