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

from mirage.core.jq.errors import JqCompileError
from mirage.core.jq.eval import (args_object, halts, jq_check, jq_eval, jq_run,
                                 references_args, stream_events, stream_reads)
from mirage.core.jq.format import error_report, format_jq_output
from mirage.core.jq.position import InputPositions
from mirage.core.jq.stream import (eval_jsonl_stream, is_jsonl_path,
                                   is_streamable_jsonl_expr, parse_json_auto,
                                   parse_json_docs, parse_json_path,
                                   parse_json_text, parse_jsonl,
                                   parse_seq_docs, parse_seq_text,
                                   split_raw_lines, split_raw_text)
from mirage.core.jq.types import (DEFAULT_INDENT, STDIN_NAME, UNKNOWN_POSITION,
                                  JqError, JqHalt, JqOptions, JqRun,
                                  StreamReads)

__all__ = [
    "DEFAULT_INDENT",
    "STDIN_NAME",
    "UNKNOWN_POSITION",
    "InputPositions",
    "JqCompileError",
    "JqError",
    "JqHalt",
    "JqOptions",
    "JqRun",
    "StreamReads",
    "args_object",
    "error_report",
    "eval_jsonl_stream",
    "format_jq_output",
    "halts",
    "is_jsonl_path",
    "is_streamable_jsonl_expr",
    "jq_check",
    "jq_eval",
    "jq_run",
    "parse_json_auto",
    "parse_json_docs",
    "parse_json_path",
    "parse_json_text",
    "parse_jsonl",
    "parse_seq_docs",
    "parse_seq_text",
    "references_args",
    "stream_events",
    "stream_reads",
    "split_raw_lines",
    "split_raw_text",
]
