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

import asyncio
import re
import shlex
from collections.abc import Callable
from enum import Enum
from typing import Any

from mirage.commands.config import version_line
from mirage.commands.spec.help import render_help
from mirage.commands.spec.shell import SHELL_SPECS, parse_shell_options
from mirage.commands.spec.usage import (missing_value_error,
                                        unknown_option_error, usage_hint)
from mirage.io import IOResult
from mirage.io.stream import async_chain, materialize, yield_bytes
from mirage.io.types import ByteSource
from mirage.workspace.executor.builtins.types import BuiltinCall, Result
from mirage.workspace.session import (SessionState, reset_current_session,
                                      set_current_session)
from mirage.workspace.types import ExecutionNode

_SYNOPSIS = "xargs [OPTION]... COMMAND [INITIAL-ARGS]..."
_PROCS_MAX = 2147483647
_BLANKS = frozenset(" \t")
_SPACES = frozenset(" \t\n\v\f\r")
_QUOTES = {"'": "single", '"': "double"}
_NUMBER = re.compile(r"[ \t\n\v\f\r]*[+-]?[0-9]+")


class _State(Enum):
    NORM = "norm"
    SPACE = "space"
    QUOTE = "quote"
    BACKSLASH = "backslash"


def _refuse(stderr: str | bytes,
            exit_code: int = 1) -> tuple[None, IOResult, ExecutionNode]:
    data = stderr.encode() if isinstance(stderr, str) else stderr
    return None, IOResult(exit_code=exit_code,
                          stderr=data), ExecutionNode(command="xargs",
                                                      exit_code=exit_code)


def _count_error(raw: str,
                 name: str,
                 least: int = 1,
                 most: int | None = None) -> str | None:
    """GNU's parse_num refusal of a count, None for a valid one.

    Args:
        raw (str): the option's value as typed.
        name (str): the option letter.
        least (int): the smallest count the option takes.
        most (int | None): the largest, None when unbounded.
    """
    if not _NUMBER.fullmatch(raw):
        message = f'invalid number "{raw}" for -{name} option'
    elif int(raw) < least:
        message = f"value {raw} for -{name} option should be >= {least}"
    elif most is not None and int(raw) > most:
        message = f"value {raw} for -{name} option should be <= {most}"
    else:
        return None
    return f"xargs: {message}\n{usage_hint('xargs')}\n"


def _standard_response(
        option: str,
        warnings: str) -> tuple[ByteSource, IOResult, ExecutionNode]:
    """xargs's answer to --help or --version: stdout, exit 0.

    Args:
        option (str): "help" or "version".
        warnings (str): the option warnings printed before it.
    """
    text = (render_help("xargs", SHELL_SPECS["xargs"],
                        synopsis=_SYNOPSIS).encode()
            if option == "help" else version_line("xargs"))
    return yield_bytes(text), IOResult(
        stderr=warnings.encode() or None), ExecutionNode(command="xargs",
                                                         exit_code=0)


def _exclusive(option: str, offending: str) -> str:
    return (f"xargs: warning: options {offending} and {option} are mutually "
            f"exclusive, ignoring previous {offending} value\n")


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
    its own read had pushed; the refusal is empty otherwise. GNU 4.10.0's
    EOF check uses the rendered buffer: an empty quoted token or lone
    quote at EOF is ignored, unlike one terminated by a newline.

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


async def _run_lines(execute_fn: Callable[..., Any], lines: list[str],
                     session: SessionState, procs: int) -> list[IOResult]:
    """Run the command lines, at most ``procs`` at a time.

    GNU starts no command once one could not run (126, 127) and waits
    for those already running. Commands that run side by side each get
    a fork of the session, as GNU's children are separate processes,
    so one cannot see another's variables, and each drains inside its
    fork, since a stream can still read the ambient session. The
    results come back in input order, which is the order their output
    is written in.

    Args:
        execute_fn (Callable): shell evaluator for each line.
        lines (list[str]): the command lines, in input order.
        session (SessionState): the session the lines run in.
        procs (int): the -P count; 0 runs every line at once.
    """
    results: list[IOResult | None] = [None] * len(lines)
    upcoming = iter(range(len(lines)))
    stopped = False
    forked = procs != 1 and len(lines) > 1

    async def run(line: str) -> IOResult:
        io: IOResult
        if not forked:
            io = await execute_fn(line, session_id=session.session_id)
            return io
        token = set_current_session(session.fork())
        try:
            io = await execute_fn(line, session_id=session.session_id)
            await io.materialize_stdout()
            await io.materialize_stderr()
            return io
        finally:
            reset_current_session(token)

    async def worker() -> None:
        nonlocal stopped
        while not stopped:
            index = next(upcoming, None)
            if index is None:
                return
            try:
                io = await run(lines[index])
            except BaseException:
                stopped = True
                raise
            results[index] = io
            if io.exit_code in (126, 127):
                stopped = True

    width = (min(procs, len(lines)) if procs else len(lines)) if forked else 1
    await asyncio.gather(*(worker() for _ in range(width)))
    return [io for io in results if io is not None]


async def handle_xargs(
    execute_fn: Callable[..., Any],
    args: list[str],
    session: SessionState,
    stdin: ByteSource | None,
) -> tuple[ByteSource | None, IOResult, ExecutionNode]:
    """Run a command with words read from stdin (GNU xargs).

    The words are appended to the initial arguments, or with -I each
    input line takes the place of the string in them. Options act in
    the order given, as GNU's getopt loop reads them: -I, -L and -n
    cancel each other with GNU's warning, and --help or --version
    answers where it stands.

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
    replace: str | None = None
    max_lines = 0
    max_args = 0
    procs = 1
    warnings = ""
    delim: str | None = None
    for name, value in parse.given:
        if name in ("help", "version"):
            return _standard_response(name, warnings)
        if name == "0":
            delim = "\0"
        if name == "d" and isinstance(value, str):
            if not value:
                return _refuse(
                    warnings +
                    "xargs: Invalid input delimiter specification : "
                    "the delimiter must be either a single character or an "
                    "escape sequence starting with \\.\n")
            delim = value.replace("\\n", "\n").replace("\\t", "\t")
        if name in ("I", "i"):
            if max_args:
                warnings += _exclusive("--replace/-I/-i", "--max-args")
            if max_lines:
                warnings += _exclusive("--replace/-I/-i", "--max-lines")
            replace = value if isinstance(value, str) else "{}"
            max_lines, max_args = 0, 0
            continue
        if name not in ("L", "l", "n", "P"):
            continue
        raw = value if isinstance(value, str) else "1"
        least, most = (0, _PROCS_MAX) if name == "P" else (1, None)
        error = _count_error(raw, name, least, most)
        if error is not None:
            return _refuse(warnings + error)
        count = int(raw)
        if name == "P":
            procs = count
            continue
        if name in ("L", "l"):
            option = "-L" if name == "L" else "--max-lines/-l"
            if max_args:
                warnings += _exclusive(option, "--max-args")
            if replace is not None:
                warnings += _exclusive(option, "--replace")
            replace, max_lines, max_args = None, count, 0
            continue
        if max_lines:
            warnings += _exclusive("--max-args/-n", "--max-lines")
        max_lines = 0
        if replace is not None and count == 1:
            # GNU reads `-I {} -n1` as plain -I.
            continue
        if replace is not None:
            warnings += _exclusive("--max-args/-n", "--replace")
        replace, max_args = None, count
    if parse.invalid is not None:
        stderr, code = unknown_option_error("xargs", parse.invalid)
        return _refuse(warnings.encode() + stderr, code)
    if parse.needs_value is not None:
        stderr, code = missing_value_error("xargs", parse.needs_value)
        return _refuse(warnings.encode() + stderr, code)

    data = await materialize(stdin)
    text = (data or b"").decode(errors="replace")
    if delim is None:
        reads, quote_error = _read_lines(text, replace is not None)
    else:
        reads, quote_error = [([item], True)
                              for item in _read_items(text, delim)], ""

    command = parse.operands or ["echo"]
    if replace is not None:
        items = [word for words, _ in reads for word in words]
        if items and not replace and len(command) > 1:
            return _refuse(warnings + "xargs: command too long\n")
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

    ios = await _run_lines(execute_fn, [shlex.join(run) for run in runs],
                           session, procs)
    stdouts: list[ByteSource] = []
    merged = IOResult(stderr=warnings.encode() or None)
    for io in ios:
        if io.stdout is not None:
            stdouts.append(io.stdout)
        merged = await merged.merge(io)
    # GNU xargs stops when the command cannot run or is missing, and
    # exits 123 when any invocation fails but keeps going.
    exit_code = next(
        (io.exit_code for io in ios if io.exit_code in (126, 127)),
        123 if any(io.exit_code != 0 for io in ios) else 0)
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
