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

import json
from datetime import datetime, timezone
from typing import Any

from mirage.core.slack.scope import SearchTarget
from mirage.utils.naming import fit_id_name, make_id_name
from mirage.utils.sanitize import path_safe_name


def channel_dirname(ch: dict[str, Any]) -> str:
    """Compute the VFS dirname for a channel, of the form `name__C123`."""
    return make_id_name(
        ch.get("name", ch.get("id", "unknown")),
        ch["id"],
        path_safe=True,
    )


def dm_dirname(dm: dict[str, Any], user_map: dict[str, str]) -> str:
    """Compute the VFS dirname for a DM, of the form `username__D123`.

    Args:
        dm (dict): DM channel dict with id and user fields.
        user_map (dict[str, str]): user_id -> name lookup.

    Returns:
        str: dirname; falls back to the user id when not in user_map.
    """
    user_id = dm.get("user", "")
    display = user_map.get(user_id, user_id)
    return make_id_name(display, dm["id"], path_safe=True)


def user_filename(u: dict[str, Any]) -> str:
    """Compute the VFS filename for a user, of the form `name__U123.json`."""
    name = u.get("name", u.get("id", "unknown"))
    return make_id_name(name, u["id"], path_safe=True, suffix=".json")


def file_blob_name(file_meta: dict[str, Any]) -> str:
    """Construct a stable VFS filename for a Slack file metadata dict.

    Args:
        file_meta (dict): Slack file dict (with id, name/title fields).

    Returns:
        str: VFS filename of shape `<stem>__<F-id>.<ext>`. The stem keeps
        the original spelling, only ``/`` is replaced, and it is the only
        part trimmed to fit NAME_MAX -- the id and extension are what make
        the name resolve, so they are spent first.
    """
    raw_name = file_meta.get("name") or file_meta.get("title") or "file"
    fid = file_meta.get("id", "")
    if "." in raw_name:
        stem, _, ext = raw_name.rpartition(".")
        return fit_id_name(path_safe_name(stem), fid, f".{ext}")
    return fit_id_name(path_safe_name(raw_name), fid)


def build_query(pattern: str, scope: SearchTarget) -> str:
    """Compose a Slack search query string for a pushed-down grep/rg call.

    Args:
        pattern (str): user-supplied pattern.
        scope (SearchTarget): the Slack-side directory the grep is rooted at.

    Returns:
        str: query with optional in:#channel or in:@user prefix.
    """
    if scope.container == "channels" and scope.channel_name:
        return f"in:#{scope.channel_name} {pattern}"
    if scope.container == "dms" and scope.channel_name:
        return f"in:@{scope.channel_name} {pattern}"
    return pattern


def format_grep_results(
    raw: bytes,
    scope: SearchTarget,
    prefix: str,
) -> list[str]:
    """Format a Slack search.messages JSON response as grep-style lines.

    Args:
        raw (bytes): JSON-encoded search.messages response.
        scope (SearchTarget): the rooted scope used to compute relative paths.
        prefix (str): VFS mount prefix to prepend.

    Returns:
        list[str]: grep-formatted lines, one per match.
    """
    payload = json.loads(raw.decode())
    matches = payload.get("messages", {}).get("matches", []) or []
    lines: list[str] = []
    for msg in matches:
        ch = msg.get("channel", {}) or {}
        ch_name = ch.get("name") or scope.channel_name or ""
        ch_id = ch.get("id") or scope.channel_id or ""
        container = scope.container or "channels"
        ts_raw = msg.get("ts", "0")
        try:
            ts_float = float(ts_raw)
            date_str = (
                datetime.fromtimestamp(ts_float, tz=timezone.utc)
                .date()
                .isoformat()
            )
        except (TypeError, ValueError):
            date_str = ""
        # The dirname readdir emits, not a second spelling of it: the
        # label's byte budget depends on the id, so composing the pair here
        # reported a path that does not exist as soon as a long channel name
        # was trimmed on one side and not the other.
        dirname = (
            channel_dirname({"id": ch_id, "name": ch_name})
            if ch_id
            else path_safe_name(ch_name)
        )
        path = (
            f"{prefix}/{container}/{dirname}/{date_str}/chat.jsonl"
            if date_str
            else f"{prefix}/{container}/{dirname}"
        )
        author = msg.get("username") or msg.get("user") or "?"
        text = (msg.get("text") or "").replace("\n", " ")
        lines.append(f"{path}:[{author}] {text}")
    return lines


def format_file_grep_results(
    raw: bytes,
    scope: SearchTarget,
    prefix: str,
) -> list[str]:
    """Format a Slack search.files JSON response as grep-style lines.

    Args:
        raw (bytes): JSON-encoded search.files response.
        scope (SearchTarget): the rooted scope (must have channel_id).
        prefix (str): VFS mount prefix to prepend.

    Returns:
        list[str]: grep-formatted lines, one per file match.
    """
    payload = json.loads(raw.decode())
    matches = payload.get("files", {}).get("matches", []) or []
    lines: list[str] = []
    for f in matches:
        fid = f.get("id", "")
        title = f.get("title") or f.get("name") or fid
        blob_name = file_blob_name(f)
        ts = f.get("timestamp", 0)
        try:
            date_str = (
                datetime.fromtimestamp(float(ts), tz=timezone.utc)
                .date()
                .isoformat()
            )
        except (TypeError, ValueError):
            date_str = ""
        if not scope.channel_id:
            continue
        ch_id = scope.channel_id
        ch_name = scope.channel_name or ""
        dirname = (
            channel_dirname({"id": ch_id, "name": ch_name})
            if ch_name
            else ch_id
        )
        container = scope.container or "channels"
        path = (
            f"{prefix}/{container}/{dirname}/{date_str}/files/{blob_name}"
            if date_str
            else f"{prefix}/{container}/{dirname}/files/{blob_name}"
        )
        lines.append(f"{path}:[file] {title}")
    return lines
