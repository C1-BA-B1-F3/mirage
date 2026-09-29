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
import logging

import orjson

from mirage.core.jq.types import DEFAULT_INDENT, RS, JqError, JqHalt, JqOptions
from mirage.types import JsonValue
from mirage.utils.errors import fs_strerror

logger = logging.getLogger(__name__)

NUL = b"\x00"
NEWLINE = b"\n"
RS_BYTES = RS.encode()


def _dumps(value: JsonValue, opts: JqOptions) -> bytes:
    """Serialize one output value the way jq's dumper would.

    orjson serves the two shapes it can express (compact and the default
    two-space indent, either one with sorted keys); a tab, another
    width, or ASCII escaping falls back to the stdlib encoder, which
    renders numbers and separators identically. So does an integer past
    64 bits, which orjson cannot write and jq prints digit for digit.

    Args:
        value (object): the value to render.
        opts (JqOptions): resolved output options.
    """
    if not opts.ascii_output and not opts.tab and (opts.compact or opts.indent
                                                   == DEFAULT_INDENT):
        option = orjson.OPT_SORT_KEYS if opts.sort_keys else 0
        if not opts.compact:
            option |= orjson.OPT_INDENT_2
        try:
            return orjson.dumps(value, option=option)
        except orjson.JSONEncodeError as exc:
            logger.debug("jq: output past orjson, written by json: %s", exc)
    if opts.compact or opts.indent == 0:
        text = json.dumps(value,
                          ensure_ascii=opts.ascii_output,
                          sort_keys=opts.sort_keys,
                          separators=(",", ":"))
    else:
        text = json.dumps(value,
                          ensure_ascii=opts.ascii_output,
                          sort_keys=opts.sort_keys,
                          indent="\t" if opts.tab else " " * opts.indent)
    return text.encode()


def _terminator(opts: JqOptions) -> bytes:
    # --raw-output0 wins over -j whichever order they were typed, which
    # is what jq does.
    if opts.nul_output:
        return NUL
    return b"" if opts.join_output else NEWLINE


def format_one(value: JsonValue, opts: JqOptions) -> bytes:
    """Render one output value with its separator.

    Args:
        value (object): the value the program emitted.
        opts (JqOptions): resolved output options.
    """
    raw = value if opts.raw_output and isinstance(value, str) else None
    # -a beats -r: jq quotes and escapes a string under --ascii-output
    # even when raw output was asked for.
    if raw is not None and not opts.ascii_output:
        body = raw.encode()
    else:
        body = _dumps(value, opts)
    # RFC 7464 puts the separator before the value, not after it, and jq
    # writes none before a string it prints raw, quoted by -a or not.
    prefix = RS_BYTES if opts.seq and raw is None else b""
    return prefix + body + _terminator(opts)


def format_jq_output(outputs: list[JsonValue], opts: JqOptions) -> bytes:
    """Render every output of a jq program, one per line.

    Args:
        outputs (list[JsonValue]): values the program emitted, in order.
        opts (JqOptions): resolved output options.
    """
    return b"".join(format_one(value, opts) for value in outputs)


def error_report(position: str, error: JqError) -> str:
    """jq's report of an error no `try` caught, which it writes to stderr.

    A string message is printed the way C prints a string, so it ends at
    a NUL.

    Args:
        position (str): where jq's reader stands.
        error (JqError): the error.
    """
    if error.string:
        text = error.text.split("\0", 1)[0]
        return f"jq: error (at {position}): {text}\n"
    return f"jq: error (at {position}) (not a string): {error.text}\n"


def load_failure(name: str, exc: BaseException) -> str:
    """Why jq could not load a whole file (jv_load_file): an -f program,
    a --rawfile or a --slurpfile. It opens the file itself, so a
    directory gets words of its own instead of a failed read.

    Args:
        name (str): the file as typed.
        exc (BaseException): why it could not be read.
    """
    if isinstance(exc, IsADirectoryError):
        return f"Could not open {name}: It's a directory"
    return f"Could not open {name}: {fs_strerror(exc)}"


def halt_report(halt: JqHalt) -> str:
    """What jq writes to stderr for a halt: a string as it is, anything
    else dumped on a line of its own, and nothing for `halt` or a null.

    Args:
        halt (JqHalt): the halt.
    """
    if halt.message is None:
        return ""
    return halt.message if halt.string else f"{halt.message}\n"
