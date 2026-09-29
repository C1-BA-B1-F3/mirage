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
from collections.abc import AsyncIterator
from typing import Any

import orjson

from mirage.core.jq.eval import args_object, jq_run, references_args
from mirage.core.jq.format import error_report, format_one
from mirage.core.jq.position import value_end
from mirage.core.jq.types import RS, JqError, JqOptions
from mirage.io.async_line_iterator import AsyncLineIterator
from mirage.types import JsonValue


def parse_jsonl(raw: bytes) -> list[Any]:
    text = raw.decode("utf-8", errors="replace")
    return [orjson.loads(line) for line in text.splitlines() if line.strip()]


def parse_json_text(text: str) -> tuple[list[Any], list[int]]:
    """Parse a whitespace-separated stream of JSON values, and say where
    jq's parser holds each one whole (see value_end).

    jq reads a stream of values from any input, not one document: `.json`
    holding several values, newline-delimited JSONL, and pretty-printed
    values run together are all valid and all evaluate per document. The
    single-value case takes the fast orjson path; only a stream falls
    back to incremental decoding.

    Args:
        text (str): the whole input.

    Returns:
        tuple[list[Any], list[int]]: every decoded document, in order,
            and the index into ``text`` each one is whole at. Empty
            input holds no documents at all, which is why jq prints
            nothing and exits 0 for an empty file.
    """
    stripped = text.strip()
    if not stripped:
        return [], []
    lead = len(text) - len(text.lstrip())
    try:
        return [orjson.loads(stripped)
                ], [value_end(text, lead + len(stripped))]
    except orjson.JSONDecodeError as single_doc_error:
        first_error = single_doc_error
    decoder = json.JSONDecoder()
    docs: list[Any] = []
    ends: list[int] = []
    idx = 0
    end = len(stripped)
    while idx < end:
        try:
            doc, offset = decoder.raw_decode(stripped, idx)
        except ValueError:
            # Not a value stream either, so the input is simply invalid.
            # Re-raise the whole-document error: it is the one that names
            # the real problem, and callers match on orjson's type.
            raise first_error from None
        docs.append(doc)
        ends.append(value_end(text, lead + offset))
        idx = offset
        while idx < end and stripped[idx].isspace():
            idx += 1
    return docs, ends


def parse_json_docs(raw: bytes) -> list[Any]:
    """Parse a whitespace-separated stream of JSON values (see
    parse_json_text).

    Args:
        raw (bytes): the whole input.
    """
    return parse_json_text(raw.decode("utf-8", errors="replace"))[0]


def parse_json_auto(raw: bytes) -> JsonValue:
    docs = parse_json_docs(raw)
    if not docs:
        raise ValueError("jq: empty input")
    return docs[0] if len(docs) == 1 else docs


def parse_seq_text(text: str) -> tuple[list[Any], list[int]]:
    """Parse an RFC 7464 JSON text sequence (`--seq`), and say where jq's
    parser holds each value whole.

    Every value is introduced by RS, so anything before the first one is
    text the sequence never claimed. jq reports that as an ignored parse
    error and prints nothing for it; mirage drops it just as silently,
    which is the one divergence here.

    Args:
        text (str): the whole input.
    """
    docs: list[Any] = []
    ends: list[int] = []
    offset = 0
    for i, part in enumerate(text.split(RS)):
        start = offset
        offset += len(part) + 1
        if i == 0 or not part.strip():
            continue
        docs.append(orjson.loads(part))
        ends.append(value_end(text, start + len(part.rstrip())))
    return docs, ends


def parse_seq_docs(raw: bytes) -> list[Any]:
    """Parse an RFC 7464 JSON text sequence (see parse_seq_text).

    Args:
        raw (bytes): the whole input.
    """
    return parse_seq_text(raw.decode("utf-8", errors="replace"))[0]


def split_raw_text(text: str) -> tuple[list[str], list[int]]:
    """Split one input into the strings `jq -R` reads it as, and say
    where jq's reader holds each one: at its newline, or at the end of
    the input for a last line that has none.

    jq breaks on newlines only (never on the other separators
    ``str.splitlines`` honors) and a trailing newline ends the last line
    rather than starting an empty one.

    Args:
        text (str): one input's text.
    """
    if not text:
        return [], []
    lines = text.split("\n")
    ends: list[int] = []
    at = -1
    for line in lines:
        at += len(line) + 1
        ends.append(at)
    if lines[-1] == "":
        lines.pop()
        ends.pop()
    else:
        ends[-1] = len(text)
    return lines, ends


def split_raw_lines(raw: bytes) -> list[str]:
    """Split one input into the strings `jq -R` reads it as (see
    split_raw_text).

    Args:
        raw (bytes): one input's bytes.
    """
    return split_raw_text(raw.decode("utf-8", errors="replace"))[0]


def parse_json_path(raw: bytes, path: str) -> JsonValue:
    if path.endswith(".jsonl") or path.endswith(".ndjson"):
        return parse_jsonl(raw)
    return orjson.loads(raw)


def is_jsonl_path(path: str) -> bool:
    return path.endswith(".jsonl") or path.endswith(".ndjson")


def is_streamable_jsonl_expr(expression: str) -> bool:
    expr = expression.strip()
    if expr.startswith(".[]"):
        return True
    return False


async def eval_jsonl_stream(
    source: AsyncIterator[bytes],
    expression: str,
    opts: JqOptions,
    name: str,
) -> AsyncIterator[bytes]:
    """Evaluate a per-element program over a JSONL file, line by line.

    A stream of outputs has no room to report an error and go on, so the
    first error no `try` catches ends the command, in jq's own words.

    Args:
        source (AsyncIterator[bytes]): the file's byte chunks.
        expression (str): jq program text, already known to be one of
            the `.[]`-prefixed shapes this path can rewrite.
        opts (JqOptions): resolved options; only output ones reach here,
            since the caller keeps this path off for anything that
            changes input assembly.
        name (str): the file as the command line named it.
    """
    expr = expression.strip()
    if expr == ".[]":
        per_item = "."
    elif expr.startswith(".[] | "):
        per_item = expr[6:]
    elif expr.startswith(".[]."):
        per_item = expr[3:]
    else:
        per_item = expr

    args_value = args_object(opts) if references_args(per_item) else None
    lines = AsyncLineIterator(source)
    newlines = 0
    while True:
        line_bytes, found = await lines.read_until(b"\n")
        if not found and not line_bytes:
            return
        if found:
            newlines += 1
        text = line_bytes.decode("utf-8", errors="replace").strip()
        if not text:
            continue
        run = jq_run(orjson.loads(text), per_item, opts.named_args, None,
                     args_value)
        for value in run.outputs:
            yield format_one(value, opts)
        if isinstance(run.stop, JqError):
            raise ValueError(
                error_report(f"{name}:{newlines}", run.stop).rstrip("\n"))
