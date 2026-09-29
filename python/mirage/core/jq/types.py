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

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from mirage.types import JsonValue

DEFAULT_INDENT = 2

# What jq names standard input when it reports where it stands, and what
# it reports before it has read any input at all.
STDIN_NAME = "<stdin>"
UNKNOWN_POSITION = "<unknown>"


@dataclass(frozen=True, slots=True)
class JqError:
    """An error no `try` caught, which ends one run: jq reports it and
    goes on with the next document.

    Args:
        text (str): the message as jq prints it: a string as it is,
            anything else in jq's own compact dump.
        string (bool): whether the message was a string, which jq's
            report says when it was not.
    """

    text: str
    string: bool


@dataclass(frozen=True, slots=True)
class JqHalt:
    """`halt` or `halt_error`, which end the whole invocation.

    Args:
        message (str | None): halt_error's input as jq prints it (a
            string as it is, anything else in jq's compact dump), or None
            for `halt` and for a null input, which print nothing.
        string (bool): whether that input was a string, which jq prints
            with no newline of its own.
        code (float | None): the exit code `halt_error` named, or None
            for `halt`.
    """

    message: str | None
    string: bool
    code: float | None


@dataclass(frozen=True, slots=True)
class JqRun:
    """What one run of a program printed, and what ended it early.

    Args:
        outputs (list[JsonValue]): every value it printed, in order.
        stop (JqError | JqHalt | None): the error or the halt that ended
            it, or None when it ran to its end.
    """

    outputs: list[JsonValue]
    stop: JqError | JqHalt | None = None


@dataclass(frozen=True, slots=True)
class StreamReads:
    """Which of the builtins that read the input stream a program calls.

    Args:
        input (bool): `input`, which takes the next unread document.
        inputs (bool): `inputs`, which yields every unread document.
    """

    input: bool
    inputs: bool


# The record separator an application/json-seq stream puts before every
# value (RFC 7464).
RS = "\x1e"


@dataclass(frozen=True, slots=True)
class JqOptions:
    """One jq invocation's resolved options.

    The command line's implications are already applied by the caller
    (``-j`` and ``--raw-output0`` imply ``-r``, ``--tab`` and
    ``--indent`` resolve into one indent width), so every consumer reads
    plain fields.

    Args:
        null_input (bool): -n, run the program once against null and
            never read the inputs as the program's input.
        raw_input (bool): -R, each input line is a string instead of a
            JSON document.
        slurp (bool): -s, collapse the whole input stream into one
            value (an array of documents, or one string under -R).
        stream (bool): --stream, replace each input document with its
            [path, leaf] events, the same ones `tostream` emits.
        seq (bool): --seq, read and write RFC 7464 JSON text sequences
            (every value preceded by RS).
        raw_output (bool): -r, print a string output unquoted.
        join_output (bool): -j, write no separator after an output.
        nul_output (bool): --raw-output0, write a NUL after an output.
        compact (bool): -c, one line of JSON per output.
        ascii_output (bool): -a, escape every non-ASCII character. jq
            prints strings quoted under -a even with -r.
        sort_keys (bool): -S, sort object keys.
        tab (bool): indent with one tab per level.
        indent (int): spaces per indent level when not compact.
        exit_status (bool): -e, derive the exit code from the last
            output value.
        named_args (Mapping[str, Any]): --arg / --argjson / --rawfile /
            --slurpfile bindings, as the values $name resolves to.
        positional_args (tuple[Any, ...]): --args / --jsonargs values, in
            order, as $ARGS.positional reports them.
    """

    null_input: bool = False
    raw_input: bool = False
    slurp: bool = False
    stream: bool = False
    seq: bool = False
    raw_output: bool = False
    join_output: bool = False
    nul_output: bool = False
    compact: bool = False
    ascii_output: bool = False
    sort_keys: bool = False
    tab: bool = False
    indent: int = DEFAULT_INDENT
    exit_status: bool = False
    named_args: Mapping[str, Any] = field(default_factory=dict)
    positional_args: tuple[Any, ...] = ()
