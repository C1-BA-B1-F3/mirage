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

import re
import shlex
from collections.abc import Callable
from enum import Enum
from typing import Any

from mirage.commands.spec.shell import SHELL_SPECS, parse_shell_options
from mirage.io import IOResult
from mirage.io.stream import async_chain, materialize
from mirage.io.types import ByteSource
from mirage.workspace.executor.builtins.types import BuiltinCall, Result
from mirage.workspace.session import SessionState
from mirage.workspace.types import ExecutionNode

_UNSUPPORTED = ("P", )
_BLANKS = frozenset(" \t")
_SPACES = frozenset(" \t\n\v\f\r")
_QUOTES = {"'": "single", '"': "double"}
_NUMBER = re.compile(r"[ \t\n\v\f\r]*[+-]?[0-9]+")


class _State(Enum):
    NORM = "norm"
    SPACE = "space"
    QUOTE = "quote"
    BACKSLASH = "backslash"


def _usage_error(message: str) -> tuple[None, IOResult, ExecutionNode]:
    stderr = f"xargs: {message}\n".encode()
    return None, IOResult(exit_code=1,
                          stderr=stderr), ExecutionNode(command="xargs",
                                                        exit_code=1)


def _count_error(raw: str, name: str) -> str | None:
    """GNU's refusal of a -n or -L count, None for a valid one.

    Args:
        raw (str): the option's value as typed.
        name (str): the option letter.
    """
    if not _NUMBER.fullmatch(raw):
        return f'invalid number "{raw}" for -{name} option'
    if int(raw) < 1:
        return f"value {raw} for -{name} option should be >= 1"
    return None


def _exclusive(option: str, offending: str) -> str:
    return (f"xargs: warning: options {offending} and {option} are mutually "
            f"exclusive, ignoring previous {offending} value\n")


def _delimiter(flags: dict[str, str | bool]) -> str | None:
    if flags.get("0") is True:
        return "\0"
    delim = flags.get("d")
    if isinstance(delim, str):
        return delim.replace("\\n", "\n").replace("\\t", "\t")
    return None


def _read_items(text: str, delim: str) -> list[str]:
    """GNU's read_string: every delimiter ends an item, empty ones too.

    Args:
        text (str): the whole input.
        delim (str): the item terminator.
    """
    items = text.split(delim)
    if not items[-1]:
        items.pop()
    return items


def _read_lines(text: str,
                replace: bool) -> tuple[list[tuple[list[str], bool]], str]:
    """GNU's read_line over the whole input.

    One entry per read: the words it pushed and whether the newline
    ending it counts as a line for -L. Blanks separate words and a
    newline ends the read; quotes and backslashes are removed; leading
    blanks and blank lines are skipped, and a line whose last character
    is a blank runs on into the next one. Under -I only a newline ends
    the word, so the read is the whole line. An unmatched quote ends the
    reading with GNU's refusal, after the reads before it and the words
    its own read had pushed; the refusal is empty otherwise.

    Args:
        text (str): the whole input.
        replace (bool): whether -I is in force.
    """
    reads: list[tuple[list[str], bool]] = []
    words: list[str] = []
    buf: list[str] = []
    state = _State.SPACE
    quote = ""
    prev = ""
    for c in text:
        before, prev = prev, c
        if state is _State.SPACE:
            if c in _SPACES:
                continue
            state = _State.NORM
        if state is _State.NORM:
            if c == "\n":
                words.append("".join(buf))
                reads.append((words, before not in _BLANKS))
                words, buf, state = [], [], _State.SPACE
                continue
            if not replace and c in _BLANKS:
                words.append("".join(buf))
                buf, state = [], _State.SPACE
                continue
            if c == "\\":
                state = _State.BACKSLASH
                continue
            if c in _QUOTES:
                state, quote = _State.QUOTE, c
                continue
        elif state is _State.QUOTE:
            if c == "\n":
                reads.append((words, False))
                return reads, _unmatched(quote)
            if c == quote:
                state = _State.NORM
                continue
        else:
            state = _State.NORM
        buf.append(c)
    if buf and state is _State.QUOTE:
        reads.append((words, False))
        return reads, _unmatched(quote)
    if buf:
        words.append("".join(buf))
    if words:
        reads.append((words, False))
    return reads, ""


def _unmatched(quote: str) -> str:
    return (f"xargs: unmatched {_QUOTES[quote]} quote; by default quotes are "
            "special to xargs unless you use the -0 option\n")


def _batch_reads(reads: list[tuple[list[str], bool]], max_lines: int,
                 max_args: int) -> tuple[list[list[str]], list[str]]:
    """GNU's exec points without -I, and the words left pending.

    A batch runs once it holds -n words or -L lines.

    Args:
        reads (list[tuple[list[str], bool]]): the reader's entries.
        max_lines (int): the -L count, 0 when unset.
        max_args (int): the -n count, 0 when unset.
    """
    batches: list[list[str]] = []
    pending: list[str] = []
    lines = 0
    for words, counted in reads:
        for word in words:
            pending.append(word)
            if max_args and len(pending) == max_args:
                batches.append(pending)
                pending = []
        if counted:
            lines += 1
        if max_lines and lines >= max_lines:
            batches.append(pending)
            pending, lines = [], 0
    return batches, pending


async def handle_xargs(
    execute_fn: Callable[..., Any],
    args: list[str],
    session: SessionState,
    stdin: ByteSource | None,
) -> tuple[ByteSource | None, IOResult, ExecutionNode]:
    """Run a command with words read from stdin (GNU xargs).

    The words are appended to the initial arguments, or with -I each
    input line takes the place of the string in them. -I, -L and -n
    cancel each other, the later one winning with GNU's warning; an
    option given twice counts where it was last given, so it warns
    once where GNU warns for each occurrence.

    GNU xargs execs the command directly, so every input word must
    reach it as exactly one argv token. The inner line is built with
    shlex.join: a plain join would be re-parsed by the shell, splitting
    words with whitespace and executing $(...) found in input.

    Args:
        execute_fn (Callable): shell evaluator for the inner line.
        args (list[str]): options, then command name and initial
            arguments; the command defaults to ["echo"] like GNU.
        session (SessionState): shell session state.
        stdin (ByteSource | None): input whose words become arguments.
    """
    parse = parse_shell_options(SHELL_SPECS["xargs"], args or [])
    if parse.invalid is not None:
        if parse.invalid.startswith("--"):
            return _usage_error(f"unrecognized option '{parse.invalid}'")
        return _usage_error(f"invalid option -- '{parse.invalid}'")
    if parse.needs_value is not None:
        return _usage_error(
            f"option requires an argument -- '{parse.needs_value}'")
    for name in _UNSUPPORTED:
        if name in parse.flags:
            return _usage_error(f"unsupported option -- '{name}'")
    replace: str | None = None
    max_lines = 0
    max_args = 0
    warnings: list[str] = []
    for name, value in parse.flags.items():
        if not isinstance(value, str) or name not in ("I", "L", "n"):
            continue
        if name == "I":
            if max_args:
                warnings.append(_exclusive("--replace/-I/-i", "--max-args"))
            if max_lines:
                warnings.append(_exclusive("--replace/-I/-i", "--max-lines"))
            replace, max_lines, max_args = value, 0, 0
            continue
        error = _count_error(value, name)
        if error is not None:
            return _usage_error(error)
        if name == "L":
            if max_args:
                warnings.append(_exclusive("-L", "--max-args"))
            if replace is not None:
                warnings.append(_exclusive("-L", "--replace"))
            replace, max_lines, max_args = None, int(value), 0
            continue
        if max_lines:
            warnings.append(_exclusive("--max-args/-n", "--max-lines"))
        max_lines = 0
        if replace is not None and int(value) == 1:
            # GNU reads `-I {} -n1` as plain -I.
            continue
        if replace is not None:
            warnings.append(_exclusive("--max-args/-n", "--replace"))
        replace, max_args = None, int(value)

    data = await materialize(stdin)
    text = (data or b"").decode(errors="replace")
    delim = _delimiter(parse.flags)
    if delim is None:
        reads, quote_error = _read_lines(text, replace is not None)
    else:
        reads, quote_error = [([item], True)
                              for item in _read_items(text, delim)], ""

    command = parse.operands or ["echo"]
    if replace is not None:
        items = [word for words, _ in reads for word in words]
        if items and not replace and len(command) > 1:
            return _usage_error("command too long")
        runs = [[
            command[0], *(arg.replace(replace, item) for arg in command[1:])
        ] for item in items]
    else:
        batches, pending = _batch_reads(reads, max_lines, max_args)
        if quote_error:
            # GNU runs what it had read unless -L holds whole lines.
            if pending and not max_lines:
                batches.append(pending)
        elif pending or not (batches or parse.flags.get("r") is True):
            batches.append(pending)
        runs = [[*command, *batch] for batch in batches]

    stdouts: list[ByteSource] = []
    merged = IOResult(stderr="".join(warnings).encode() or None)
    exit_code = 0
    for run in runs:
        io = await execute_fn(shlex.join(run), session_id=session.session_id)
        if io.stdout is not None:
            stdouts.append(io.stdout)
        merged = await merged.merge(io)
        if io.exit_code in (126, 127):
            # GNU xargs stops when the command cannot run or is missing.
            exit_code = io.exit_code
            break
        if io.exit_code != 0:
            # GNU exits 123 when any invocation fails, but keeps going.
            exit_code = 123
    if quote_error and exit_code not in (126, 127):
        merged = await merged.merge(IOResult(stderr=quote_error.encode()))
        exit_code = 1
    merged.exit_code = exit_code
    out = async_chain(*stdouts) if stdouts else None
    return out, merged, ExecutionNode(command="xargs", exit_code=exit_code)


async def xargs_builtin(call: BuiltinCall) -> Result:
    """The ``xargs`` arm.

    Args:
        call (BuiltinCall): the invocation.
    """
    return await handle_xargs(call.execute_fn, list(call.argv.args),
                              call.session, call.stdin)
