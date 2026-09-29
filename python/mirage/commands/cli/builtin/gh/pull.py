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

from mirage.commands.cli.builtin.gh.accessor import (body_value, camel,
                                                     list_limit, repo_for,
                                                     repo_number, text_out,
                                                     typed_out)
from mirage.commands.cli.builtin.gh.issue import comments_for, comments_text
from mirage.commands.cli.types import CLIInvocation
from mirage.commands.spec.flag_view import FlagView
from mirage.core.github.config import GhConfig
from mirage.core.github.pull import (comment_pull, create_pull, diff_pull,
                                     edit_pull, get_pull, list_pulls,
                                     merge_pull, pull_checks)
from mirage.core.github.repo import RepoRef
from mirage.io.types import ByteSource, IOResult
from mirage.types import JsonValue

PR_FIELDS = ("additions", "author", "baseRefName", "body", "changedFiles",
             "closed", "createdAt", "deletions", "headRefName", "headRefOid",
             "isDraft", "labels", "mergeable", "mergedAt", "number", "state",
             "title", "updatedAt", "url")
CHECK_FIELDS = ("bucket", "completedAt", "description", "event", "link",
                "name", "startedAt", "state", "workflow")
BUCKETS = {
    "success": "pass",
    "neutral": "skipping",
    "skipped": "skipping",
    "action_required": "fail",
    "error": "fail",
    "failure": "fail",
    "timed_out": "fail",
    "cancelled": "cancel",
}


def _pull(value: JsonValue) -> dict[str, Any]:
    row = camel(value)
    result = row if isinstance(row, dict) else {}
    base = result.pop("base", None)
    head = result.pop("head", None)
    if isinstance(base, dict):
        result["baseRefName"] = base.get("ref")
    if isinstance(head, dict):
        result["headRefName"] = head.get("ref")
        result["headRefOid"] = head.get("sha")
    if "draft" in result:
        result["isDraft"] = result.pop("draft")
    result["closed"] = str(result.get("state", "")).lower() == "closed"
    return result


def _list_text(rows: list[dict[str, Any]]) -> str:
    return "".join(f'{row.get("number", "")}\t'
                   f'{str(row.get("state", "")).upper()}\t'
                   f'{row.get("title", "")}\t'
                   f'{row.get("headRefName", "")}\n' for row in rows)


def _view_text(row: dict[str, Any]) -> str:
    author = row.get("author")
    login = author.get("login", "") if isinstance(author, dict) else ""
    return (f'title:\t{row.get("title", "")}\n'
            f'state:\t{str(row.get("state", "")).upper()}\n'
            f'author:\t{login}\nbase:\t{row.get("baseRefName", "")}\n'
            f'head:\t{row.get("headRefName", "")}\n--\n'
            f'{row.get("body", "")}\n')


def _target(inv: CLIInvocation[GhConfig], fl: FlagView) -> tuple[RepoRef, int]:
    return repo_number(inv, fl, inv.texts[0] if inv.texts else None,
                       "pull request", "pull")


async def list_cmd(
        inv: CLIInvocation[GhConfig]) -> tuple[ByteSource | None, IOResult]:
    fl = FlagView(inv.flags)
    wanted = fl.as_str("state") or "open"
    params: dict[str, str] = {
        "state": "closed" if wanted == "merged" else wanted
    }
    for name in ("base", "head"):
        value = fl.as_str(name)
        if value:
            params[name] = value
    include = ((lambda row: row.get("merged_at") is not None)
               if wanted == "merged" else None)
    values = await list_pulls(inv.config,
                              repo_for(inv, fl),
                              params,
                              list_limit(fl, 30),
                              include=include)
    rows = [_pull(value) for value in values]
    return await typed_out(rows, fl, _list_text(rows), PR_FIELDS)


async def view_cmd(
        inv: CLIInvocation[GhConfig]) -> tuple[ByteSource | None, IOResult]:
    fl = FlagView(inv.flags)
    ref, number = _target(inv, fl)
    row = _pull(await get_pull(inv.config, ref, number))
    comments = await comments_for(inv, fl, ref, number)
    if comments is not None:
        row["comments"] = comments
    return await typed_out(
        row, fl,
        comments_text(comments or []) if fl.as_bool("comments") else
        _view_text(row), (*PR_FIELDS, "comments"))


async def create_cmd(
        inv: CLIInvocation[GhConfig]) -> tuple[ByteSource | None, IOResult]:
    fl = FlagView(inv.flags)
    required = {name: fl.as_str(name) for name in ("title", "head", "base")}
    missing = next((name for name, value in required.items() if not value),
                   None)
    if missing:
        raise ValueError(f"--{missing} is required in noninteractive mode")
    body_text = await body_value(inv, fl, required=True)
    body: dict[str, JsonValue] = {
        "title": required["title"] or "",
        "head": required["head"] or "",
        "base": required["base"] or "",
        "body": body_text or "",
        "draft": fl.as_bool("draft"),
        "maintainer_can_modify": not fl.as_bool("no_maintainer_edit"),
    }
    created = _pull(await create_pull(inv.config, repo_for(inv, fl), body))
    return text_out(f'{created.get("url", "")}\n')


async def edit_cmd(
        inv: CLIInvocation[GhConfig]) -> tuple[ByteSource | None, IOResult]:
    fl = FlagView(inv.flags)
    body: dict[str, JsonValue] = {}
    for name in ("title", "base"):
        value = fl.as_str(name)
        if value is not None:
            body[name] = value
    text = await body_value(inv, fl)
    if text is not None:
        body["body"] = text
    if not body:
        raise ValueError("no pull request fields to edit")
    ref, number = _target(inv, fl)
    edited = _pull(await edit_pull(inv.config, ref, number, body))
    return text_out(f'{edited.get("url", "")}\n')


async def merge_cmd(
        inv: CLIInvocation[GhConfig]) -> tuple[ByteSource | None, IOResult]:
    fl = FlagView(inv.flags)
    methods = [
        name for name in ("merge", "rebase", "squash") if fl.as_bool(name)
    ]
    if len(methods) > 1:
        raise ValueError("choose only one merge strategy")
    body: dict[str, JsonValue] = {
        "merge_method": methods[0] if methods else "merge"
    }
    if fl.as_str("subject") is not None:
        body["commit_title"] = fl.as_str("subject") or ""
    message = await body_value(inv, fl)
    if message is not None:
        body["commit_message"] = message
    if fl.as_str("match_head_commit") is not None:
        body["sha"] = fl.as_str("match_head_commit") or ""
    ref, number = _target(inv, fl)
    await merge_pull(inv.config, ref, number, body)
    return text_out(f"✓ Merged pull request {ref.owner}/{ref.repo}#{number}\n")


async def close_cmd(
        inv: CLIInvocation[GhConfig]) -> tuple[ByteSource | None, IOResult]:
    fl = FlagView(inv.flags)
    ref, number = _target(inv, fl)
    edited = _pull(await edit_pull(inv.config, ref, number,
                                   {"state": "closed"}))
    return text_out(f"✓ Closed pull request {ref.owner}/{ref.repo}#{number} "
                    f'({edited.get("title", "")})\n')


async def comment_cmd(
        inv: CLIInvocation[GhConfig]) -> tuple[ByteSource | None, IOResult]:
    fl = FlagView(inv.flags)
    body = await body_value(inv, fl, required=True)
    ref, number = _target(inv, fl)
    comment = _pull(await comment_pull(inv.config, ref, number, body or ""))
    return text_out(f'{comment.get("url", "")}\n')


async def diff_cmd(
        inv: CLIInvocation[GhConfig]) -> tuple[ByteSource | None, IOResult]:
    fl = FlagView(inv.flags)
    ref, number = _target(inv, fl)
    value = await diff_pull(inv.config, ref, number)
    return text_out(value if value.endswith("\n") else f"{value}\n")


def _check(value: dict[str, Any]) -> dict[str, Any]:
    row = camel(value)
    result = row if isinstance(row, dict) else {}
    result["link"] = result.pop("detailsUrl", "")
    result["description"] = result.get("output", {}).get(
        "summary", "") if isinstance(result.get("output"), dict) else ""
    conclusion = str(result.get("conclusion") or "")
    state = conclusion or str(result.get("status") or "")
    result["state"] = state
    result["bucket"] = BUCKETS.get(state, "pending")
    app = result.get("app")
    result["workflow"] = app.get("name", "") if isinstance(app, dict) else ""
    return result


async def checks_cmd(
        inv: CLIInvocation[GhConfig]) -> tuple[ByteSource | None, IOResult]:
    fl = FlagView(inv.flags)
    ref, number = _target(inv, fl)
    rows = [
        _check(value) for value in await pull_checks(inv.config, ref, number)
    ]
    human = "".join(f'{row.get("name", "")}\t{row.get("state", "")}\t'
                    f'{row.get("link", "")}\n' for row in rows)
    out, io = await typed_out(rows, fl, human, CHECK_FIELDS)
    buckets = {row.get("bucket") for row in rows}
    if "fail" in buckets:
        io.exit_code = 1
    elif "pending" in buckets:
        io.exit_code = 8
    return out, io
