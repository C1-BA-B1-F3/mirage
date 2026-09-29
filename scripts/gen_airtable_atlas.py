"""Rebuild the Airtable recording corpus; never read replies from the fake.

Run with Python and pyarrow installed, passing --share DIR (the output of
integ/scripts/capture_airtable_atlas.ts) and optionally --parquet PATH to use
a local copy. MCP-Atlas (ScaleAI, CC-BY-4.0) recorded
@felores/airtable-mcp-server@0.3.0 against one base, "Car Dealership", which
it ships as a share link to copy rather than as an export file. The base is
converted from the share's own read format to the public API's, and is
directly seedable by the Airtable fake.
"""

import argparse
import hashlib
import json
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "integ" / "truth" / "airtable_atlas.json"
REVISION = "8c563b55d7c967755f474299848049834d624617"
PARQUET_URL = ("https://huggingface.co/datasets/ScaleAI/MCP-Atlas/resolve/"
               f"{REVISION}/MCP-Atlas.parquet")
BASE_ID = "appIF9byLfQwdHqE2"
SHARE_URL = f"https://airtable.com/{BASE_ID}/shr1KTZOgPl0qQmA8"
TITLE_SUFFIX = " - Airtable"
# The account the fake answers for. The share names only the owner's user
# id; no recorded tool reads the account, so its name and email are the
# fake's own.
TOKEN = "patAtlasCarDealer.fake"
EMAIL = "atlas@example.com"
NAME = "MCP-Atlas"
Json = dict[str, Any]


def load_calls(parquet: Path) -> list[Json]:
    """Read every Airtable call/reply pair, in dataset order.

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
            if function is None or not function["name"].startswith(
                    "airtable_"):
                continue
            content = message["content"]
            if len(content) != 1 or content[0]["type"] != "text":
                raise ValueError("Expected one JSON text reply")
            calls.append({
                "task": row["TASK"],
                "tool": function["name"][len("airtable_"):],
                "args": json.loads(function["arguments"]),
                "reply": content[0]["text"],
            })
    if len(calls) != 263:
        raise ValueError(
            f"Expected 263 pinned Airtable calls, got {len(calls)}")
    return calls


def color(internal: str) -> str:
    """Name a choice colour as the public API does.

    Args:
        internal (str): the share format's colour, e.g. `blue`.
    """
    if internal.endswith("Medium"):
        return internal[:-len("Medium")] + "Light1"
    return internal + "Light2"


def field(column: Json) -> Json:
    """Render one column as the public API's field.

    Args:
        column (Json): the share format's column.
    """
    kind = column["type"]
    options = column.get("typeOptions") or {}
    out: Json = {"type": kind, "id": column["id"], "name": column["name"]}
    if kind == "select":
        out["type"] = "singleSelect"
        out["options"] = {
            "choices": [{
                "id": options["choices"][choice]["id"],
                "name": options["choices"][choice]["name"],
                "color": color(options["choices"][choice]["color"]),
            } for choice in options["choiceOrder"]]
        }
    elif kind == "number":
        precision = (0 if options["format"] == "integer" else
                     options["precision"])
        out["options"] = {"precision": precision}
    elif kind == "checkbox":
        out["options"] = {
            "icon": options["icon"],
            "color": options["color"] + "Bright"
        }
    elif kind == "date":
        if options != {"isDateTime": False, "dateFormat": "ISO"}:
            raise ValueError(f"Unexpected date options {options}")
        out["options"] = {
            "dateFormat": {
                "name": "iso",
                "format": "YYYY-MM-DD"
            }
        }
    elif kind != "multilineText":
        raise ValueError(f"Unhandled column type {kind}")
    return out


def cell(column: Json, value: Any) -> Any:
    """Render one cell as the public API's value, None for an empty one.

    Args:
        column (Json): the share format's column.
        value (Any): the share format's cell.
    """
    if value is None or value == "" or value is False:
        return None
    if column["type"] == "select":
        return column["typeOptions"]["choices"][value]["name"]
    if column["type"] == "date":
        return value[:10]
    return value


def base(share: Path) -> Json:
    """Build the base, fields and records in public-API shape.

    Records are in the base's own row order, the Grid view's, which the
    share reads in; the fake answers a list with no view in record-id
    order, as live Airtable does.

    Args:
        share (Path): the capture directory.
    """
    html = (share / "share.html").read_text()
    title = html.split('<meta property="og:title" content="', 1)[1]
    title = title.split('"', 1)[0]
    if not title.endswith(TITLE_SUFFIX):
        raise ValueError(f"Unexpected share title {title!r}")
    schema = json.loads((share / "schema.json").read_text())["data"]
    tables = []
    for table in schema["tableSchemas"]:
        read = json.loads((share / f"{table['id']}.json").read_text())
        rows = read["data"]["tableDatas"][0]["rows"]
        records = []
        for row in rows:
            fields = {}
            for column in table["columns"]:
                value = cell(column,
                             row["cellValuesByColumnId"].get(column["id"]))
                if value is not None:
                    fields[column["name"]] = value
            records.append({
                "id": row["id"],
                "createdTime": row["createdTime"],
                "fields": fields,
            })
        tables.append({
            "id":
            table["id"],
            "name":
            table["name"],
            "primaryFieldId":
            table["primaryColumnId"],
            "fields": [field(column) for column in table["columns"]],
            "views": [{
                "id": view["id"],
                "name": view["name"],
                "type": view["type"],
            } for view in table["views"]],
            "records":
            records,
        })
    owner = schema["tableSchemas"][0]["columns"][0]["initialCreatedByUserId"]
    return {
        "users": [{
            "id": owner,
            "email": EMAIL,
            "name": NAME
        }],
        "tokens": [{
            "token": TOKEN,
            "userId": owner
        }],
        "bases": [{
            "id": BASE_ID,
            "name": title[:-len(TITLE_SUFFIX)],
            "permissionLevel": "create",
            "tables": tables,
        }],
    }


def digest(share: Path) -> str:
    """Hash the capture's read replies, in name order.

    Args:
        share (Path): the capture directory.
    """
    sha = hashlib.sha256()
    for path in sorted(share.glob("*.json")):
        rows = json.loads(path.read_text())["data"]
        body = rows.get("tableSchemas") if path.name == "schema.json" else (
            rows["tableDatas"][0]["rows"])
        sha.update(path.name.encode())
        sha.update(json.dumps(body, sort_keys=True).encode())
    return sha.hexdigest()


def dumps(corpus: Json) -> str:
    """Indent the corpus as the other truth files are, a record per line.

    Twenty thousand records at one key per line would be most of the file;
    one compact line each keeps a changed record a one-line diff.

    Args:
        corpus (Json): the corpus.
    """
    lines: dict[str, str] = {}
    for table in corpus["workspace"]["bases"][0]["tables"]:
        key = f"@records:{table['id']}"
        lines[key] = ",\n".join(
            " " * 12 + json.dumps(r, ensure_ascii=False, separators=(",", ":"))
            for r in table["records"])
        table["records"] = key
    text = json.dumps(corpus, ensure_ascii=False, indent=2)
    for key, body in lines.items():
        text = text.replace(json.dumps(key),
                            "[\n" + body + "\n" + " " * 10 + "]")
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--share", type=Path, required=True)
    parser.add_argument("--parquet", type=Path)
    opts = parser.parse_args()
    with tempfile.TemporaryDirectory() as scratch:
        parquet = opts.parquet or Path(scratch) / "atlas.parquet"
        if opts.parquet is None:
            urllib.request.urlretrieve(PARQUET_URL, parquet)
        calls = load_calls(parquet)
    seed = base(opts.share)
    corpus = {
        "source": {
            "dataset":
            "ScaleAI/MCP-Atlas",
            "revision":
            REVISION,
            "license":
            "CC-BY-4.0",
            "server":
            "@felores/airtable-mcp-server@0.3.0",
            "share_url":
            SHARE_URL,
            "share_sha256":
            digest(opts.share),
            "notes": [
                "The base is read from the share link Atlas publishes in "
                "place of an export, through the share page's own read "
                "endpoint, and converted to the public API's field and "
                "value shapes.",
                "Records are in the base's own row order, the Grid view's; "
                "every recorded call reads with no view, which live "
                "Airtable answers in record-id order.",
                "The account (user, token) is the fake's own: the share "
                "names only the owner's user id, and no recorded tool "
                "reads the account.",
            ],
        },
        "workspace": seed,
        "calls": calls,
    }
    OUT.write_text(dumps(corpus) + "\n")


if __name__ == "__main__":
    main()
