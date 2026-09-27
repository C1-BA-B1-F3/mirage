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
import posixpath
import re
from collections.abc import Iterable
from typing import Any

from mirage.commands.cli.types import CLIInvocation
from mirage.commands.errors import UsageError
from mirage.commands.spec.flag_view import FlagView
from mirage.commands.spec.types import FlagValue
from mirage.core.github.config import GhConfig
from mirage.core.github.repo import RepoRef, parse_repo
from mirage.core.jq import jq_eval
from mirage.io.stream import materialize, yield_bytes
from mirage.io.types import ByteSource, IOResult
from mirage.types import JsonValue, PathSpec
from mirage.utils.errors import fs_strerror


def gh_repo(config: GhConfig, spec: str | None) -> RepoRef:
    """The repository a line is about.

    The operand when it named one, the install's own otherwise. Real gh
    resolves this from the current git remote, which a workspace has no
    equivalent of, so the config carries it.

    Args:
        config (GhConfig): the install's configuration.
        spec (str | None): the repository the line named, if any.

    Returns:
        RepoRef: the owner and repository names.

    Raises:
        ValueError: neither the line nor the install named one.
    """
    named = spec if spec else config.repo
    if not named:
        raise ValueError(
            "no repository given; pass one or set `repo` on the install")
    return parse_repo(named)


def json_out(value: JsonValue) -> tuple[ByteSource | None, IOResult]:
    text = ("" if value is None else
            f"{json.dumps(value, indent=2, ensure_ascii=False)}\n")
    return yield_bytes(text.encode()), IOResult()


def text_out(text: str) -> tuple[ByteSource | None, IOResult]:
    return yield_bytes(text.encode()), IOResult()


def repo_for(inv: CLIInvocation[GhConfig], fl: FlagView) -> RepoRef:
    """Resolve a typed verb's shared `-R/--repo` target."""
    return gh_repo(inv.config, fl.as_str("repo"))


def list_limit(fl: FlagView, default: int) -> int:
    """Preserve an explicit zero while applying a list command's default."""
    value = fl.as_int("limit")
    return default if value is None else value


def repo_number(inv: CLIInvocation[GhConfig], fl: FlagView, value: str | None,
                label: str, url_kind: str) -> tuple[RepoRef, int]:
    """Resolve a numeric subject or a full GitHub subject URL atomically."""
    raw = value or ""
    if raw.isdigit():
        return repo_for(inv, fl), int(raw)
    match = re.fullmatch(
        r"https?://[^/]+/([^/]+)/([^/]+)/(issues|pull)/(\d+)/?", raw)
    if match is None or match.group(3) != url_kind:
        raise ValueError(f"a {label} number is required")
    return parse_repo(f"{match.group(1)}/{match.group(2)}"), int(
        match.group(4))


def csv_values(values: Iterable[str]) -> list[str]:
    """Expand repeatable comma-separated gh flags, preserving order."""
    return [
        item.strip() for value in values for item in value.split(",")
        if item.strip()
    ]


async def read_cli_file(inv: CLIInvocation[GhConfig], raw: FlagValue,
                        option: str) -> bytes:
    """Read a path-valued CLI option from the VFS, or `-` from stdin."""
    if not isinstance(raw, (str, PathSpec)):
        raise ValueError(f"{option} expects a file")
    path = raw.raw_path if isinstance(raw, PathSpec) else raw
    if path == "-":
        if inv.stdin is None:
            raise ValueError(f"{option} needs standard input")
        return await materialize(inv.stdin)
    spec = raw if isinstance(raw, PathSpec) else PathSpec.from_str_path(
        posixpath.normpath(posixpath.join(inv.env.get("PWD", "/"), raw)))
    if inv.doors is None or inv.doors.dispatch is None:
        raise ValueError(f"{option} needs a workspace to read files from")
    try:
        data, _ = await inv.doors.dispatch("read", spec)
        return await materialize(data)
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise ValueError(f"read {path}: {fs_strerror(exc)}") from None


async def body_value(inv: CLIInvocation[GhConfig],
                     fl: FlagView,
                     *,
                     value: str = "body",
                     file: str = "body_file",
                     required: bool = False) -> str | None:
    """Resolve mutually exclusive inline and file/stdin text options."""
    inline = fl.as_str(value)
    source = fl.raw(file)
    if inline is not None and source is not None:
        raise UsageError(f"--{value.replace('_', '-')} and "
                         f"--{file.replace('_', '-')} are mutually exclusive")
    if inline is not None:
        return inline
    if source is not None:
        return (await read_cli_file(inv, source,
                                    f"--{file.replace('_', '-')}")).decode()
    if required:
        raise ValueError(f"--{value.replace('_', '-')} or "
                         f"--{file.replace('_', '-')} is required")
    return None


def camel_key(key: str) -> str:
    """Convert one REST snake_case key to gh's JSON field spelling."""
    head, *tail = key.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in tail)


def camel(value: Any) -> Any:
    """Recursively normalize REST objects for typed gh JSON output."""
    if isinstance(value, list):
        return [camel(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {camel_key(str(key)): camel(item) for key, item in value.items()}
    if "htmlUrl" in result:
        result["url"] = result.pop("htmlUrl")
    if "user" in result:
        result["author"] = result.pop("user")
    return result


def jq_line(value: Any) -> str:
    """Render one jq result in gh's raw-output mode."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _select(value: Any, fields: list[str]) -> Any:
    """Each row cut to the fields asked for, keys in sorted order: gh
    exports a Go map, which its JSON encoder always writes sorted.

    Args:
        value (Any): one row or a list of them.
        fields (list[str]): the ``--json`` fields.
    """
    rows = value if isinstance(value, list) else [value]
    keys = sorted(set(fields))
    selected: list[dict[str, Any]] = []
    for row in rows:
        source = row if isinstance(row, dict) else {}
        selected.append({field: source.get(field) for field in keys})
    return selected if isinstance(value, list) else selected[0]


def json_fields(fl: FlagView, allowed: Iterable[str]) -> list[str] | None:
    """The ``--json`` fields a line asked for, None without ``--json``.

    Checked before any request, as gh checks them: a field gh does not
    export is refused with gh's own message and every field it does,
    sorted, exit 1.

    Args:
        fl (FlagView): the line's flags.
        allowed (Iterable[str]): the fields the verb exports.
    """
    spelled = fl.as_str("json")
    if spelled is None:
        return None
    fields = csv_values([spelled])
    known = set(allowed)
    listing = [f"  {field}" for field in sorted(known)]
    if not fields:
        raise UsageError(
            "\n".join([
                "Specify one or more comma-separated fields for `--json`:",
                *listing
            ]), 1)
    unknown = [field for field in fields if field not in known]
    if unknown:
        raise UsageError(
            "\n".join([
                f"Unknown JSON field: {json.dumps(unknown[0])}",
                "Available fields:", *listing
            ]), 1)
    return fields


async def typed_out(
        value: Any, fl: FlagView, human: str,
        allowed: Iterable[str]) -> tuple[ByteSource | None, IOResult]:
    """Render a typed verb as stable projected JSON/jq or human text."""
    program = fl.as_str("jq")
    fields = json_fields(fl, allowed)
    if fields is None:
        if program:
            raise UsageError("--jq requires --json")
        return text_out(human)
    selected = _select(value, fields)
    if program:
        lines = "".join(f"{jq_line(item)}\n"
                        for item in jq_eval(selected, program))
        return text_out(lines)
    return json_out(selected)
