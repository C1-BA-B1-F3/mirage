"""Rebuild the Slack live-recording corpus; never read replies from the fake.

Run with Python and pyarrow installed, optionally passing --parquet PATH and
--export PATH to use local copies. MCP-Atlas (ScaleAI, CC-BY-4.0) recorded
slack-mcp-server 1.1.23. Its later workspace export shifted message timestamps
forward 161 days; subtract that offset without rounding their microseconds.
The workspace is directly seedable by the Slack fake and shared with consumers.
"""

import argparse
import csv
import hashlib
import io
import json
import re
import tempfile
import urllib.request
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "integ" / "truth" / "slack_atlas.json"
REVISION = "8c563b55d7c967755f474299848049834d624617"
EXPORT_REVISION = "c64799a8e4056582c1220e82751c445862a33308"
PARQUET_URL = ("https://huggingface.co/datasets/ScaleAI/MCP-Atlas/resolve/"
               f"{REVISION}/MCP-Atlas.parquet")
EXPORT_URL = ("https://raw.githubusercontent.com/scaleapi/mcp-atlas/"
              f"{EXPORT_REVISION}/data_exports/slack_mcp_eval_export.zip")
SHIFT_SECONDS = 161 * 86400
FILE_FIELDS = ("name", "title", "mimetype", "filetype")
Json = dict[str, Any]


def load_calls(parquet: Path) -> list[Json]:
    """Read every Slack call/reply pair, in dataset order.

    Args:
        parquet (Path): pinned MCP-Atlas dataset file.
    """
    calls: list[Json] = []
    for row in pq.read_table(parquet).to_pylist():
        pending: dict[str, Json] = {}
        for message in json.loads(row["TRAJECTORY"]):
            for call in message.get("tool_calls") or []:
                pending[call["id"]] = call["function"]
            function = pending.get(message.get("tool_call_id", ""))
            if function is None or not function["name"].startswith("slack_"):
                continue
            content = message["content"]
            if len(content) != 1 or content[0]["type"] != "text":
                raise ValueError("Expected one CSV text reply")
            calls.append({
                "task": row["TASK"],
                "tool": function["name"][len("slack_"):],
                "args": json.loads(function["arguments"]),
                "reply": content[0]["text"],
            })
    if len(calls) != 56:
        raise ValueError(f"Expected 56 pinned Slack calls, got {len(calls)}")
    return calls


def shifted(ts: str) -> str:
    seconds, fraction = ts.split(".")
    return f"{int(seconds) - SHIFT_SECONDS}.{fraction}"


def workspace(export: Path) -> Json:
    """Build seed rows, retaining activity and file metadata.

    Args:
        export (Path): pinned Slack workspace export archive.
    """
    with zipfile.ZipFile(export) as archive:
        prefix = "slack_mcp_eval_export/"
        users = json.loads(archive.read(prefix + "users.json"))
        channels = json.loads(archive.read(prefix + "channels.json"))
        messages = []
        files = []
        for channel in channels:
            raw = []
            for name in sorted(archive.namelist()):
                if name.startswith(prefix + channel["name"] +
                                   "/") and name.endswith(".json"):
                    raw.extend(json.loads(archive.read(name)))
            raw.sort(key=lambda message: message["ts"])
            private = False
            for message in raw:
                subtype = message.get("subtype")
                if subtype in ("channel_convert_to_private",
                               "channel_convert_to_public"):
                    private = subtype == "channel_convert_to_private"
                ts = shifted(message["ts"])
                messages.append({
                    "channelId":
                    channel["id"],
                    "ts":
                    ts,
                    "userId":
                    message["user"],
                    "text":
                    message.get("text", ""),
                    "type":
                    message["type"],
                    "subtype":
                    subtype,
                    "threadTs":
                    shifted(message["thread_ts"])
                    if message.get("thread_ts") else None,
                    "reactionsJson":
                    message.get("reactions", []),
                })
                for file in message.get("files", []):
                    files.append({
                        "id": file["id"],
                        "channelId": channel["id"],
                        "messageTs": ts,
                        **{
                            key: file[key]
                            for key in FILE_FIELDS
                        },
                        "content": "",
                    })
            channel["is_private"] = private
    if len(messages) != 160:
        raise ValueError(
            f"Expected 160 exported messages, got {len(messages)}")
    return {
        "users": [{
            "id": u["id"],
            "name": u["name"],
            "realName": u.get("real_name", ""),
            "email": u.get("profile", {}).get("email", ""),
            "isBot": u.get("is_bot", False),
            "deleted": u.get("deleted", False),
        } for u in users],
        "channels": [{
            "id": c["id"],
            "name": c["name"],
            "kind": "channel",
            "created": c["created"],
            "isArchived": c["is_archived"],
            "isPrivate": c["is_private"],
            "topic": c["topic"]["value"],
            "purpose": c["purpose"]["value"],
            "membersJson": c["members"],
        } for c in channels],
        "messages":
        messages,
        "files":
        files,
    }


def mark_skips(calls: list[Json], seed: Json) -> None:
    """Mark calls the recorded workspace cannot reproduce.

    Args:
        calls (list[Json]): recorded calls, annotated in place.
        seed (Json): workspace reconstructed from the export.
    """
    groups: dict[str, list[Json]] = defaultdict(list)
    for call in calls:
        if call["tool"] == "channels_list":
            groups[json.dumps(call["args"], sort_keys=True)].append(call)
    for group in groups.values():
        if len({call["reply"] for call in group}) > 1:
            for call in group:
                call["skip"] = ("Identical channel-list arguments have "
                                "contradictory live replies")
    known = {(m["channelId"], m["ts"]) for m in seed["messages"]}
    names = {"#" + c["name"]: c["id"] for c in seed["channels"]}
    channel_ids = {c["id"] for c in seed["channels"]}
    for call in calls:
        if call["tool"] == "channels_list":
            continue
        if re.fullmatch(r"\d+[dwm]", call["args"].get("limit", "")):
            call["skip"] = ("History window is relative to "
                            "the unrecorded call time")
            continue
        missing = []
        for row in csv.DictReader(io.StringIO(call["reply"])):
            channel = names.get(row["Channel"], row["Channel"])
            if (channel, row["Time"]) not in known:
                if channel in channel_ids:
                    raise ValueError(f"Export timestamp mismatch: {row}")
                missing.append(f"{row['Channel']} at {row['Time']}")
        if missing:
            call["skip"] = (
                "Reply contains messages absent from the export: " +
                ", ".join(missing))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--parquet", type=Path)
    parser.add_argument("--export", type=Path)
    opts = parser.parse_args()
    with tempfile.TemporaryDirectory() as scratch:
        parquet = opts.parquet or Path(scratch) / "atlas.parquet"
        export = opts.export or Path(scratch) / "slack.zip"
        if opts.parquet is None:
            urllib.request.urlretrieve(PARQUET_URL, parquet)
        if opts.export is None:
            urllib.request.urlretrieve(EXPORT_URL, export)
        calls = load_calls(parquet)
        seed = workspace(export)
        digest = hashlib.sha256(export.read_bytes()).hexdigest()
    mark_skips(calls, seed)
    corpus = {
        "source": {
            "dataset":
            "ScaleAI/MCP-Atlas",
            "revision":
            REVISION,
            "license":
            "CC-BY-4.0",
            "server":
            "slack-mcp-server@1.1.23",
            "export_url":
            EXPORT_URL,
            "export_sha256":
            digest,
            "message_timestamp_shift_seconds":
            -SHIFT_SECONDS,
            "notes": [
                "Channel privacy follows the last exported conversion event.",
                "Files retain metadata; the export has no file contents.",
                "Search replies ignore relevance order: "
                "Slack scores are not exported.",
            ],
        },
        "workspace": seed,
        "calls": calls,
    }
    OUT.write_text(json.dumps(corpus, ensure_ascii=False, indent=2) + "\n")
    print(f"{OUT.relative_to(ROOT)}: {len(calls)} calls, "
          f"{sum('skip' in c for c in calls)} skips")


if __name__ == "__main__":
    main()
