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

from typing import Any

from mirage.io import IOResult
from mirage.io.stream import async_chain, materialize
from mirage.policy.decisions import Decisions
from mirage.policy.types import HandOff
from mirage.shell.console import JobConsole
from mirage.shell.constants import ERREXIT_EXEMPT_TYPES
from mirage.shell.descriptors import ENCLOSING, Recorder, StreamOwner
from mirage.shell.errors import ExitSignal, ReturnSignal
from mirage.shell.helpers import get_text
from mirage.shell.node_kind import pipeline_transparent
from mirage.shell.types import NodeType as NT
from mirage.workspace.executor.builtins.exec import divert_statement
from mirage.workspace.executor.control import UNWINDING
from mirage.workspace.executor.jobs import handle_background
from mirage.workspace.executor.statement import (
    failed_read,
    fd0_binding,
    land,
    record_status,
    statement_output,
    statement_stdin,
)
from mirage.workspace.types import ExecutionNode


async def execute_program(
    recurse,
    node,
    session,
    stdin,
    call_stack,
    job_table,
    agent_id,
    dispatch=None,
    handed: HandOff | None = None,
    decisions: Decisions | None = None,
    sink: JobConsole | None = None,
) -> tuple[Any, IOResult, ExecutionNode]:
    """Execute program node (root / semicolon-separated).

    ``dispatch`` is the op door, threaded so an active ``exec`` redirect
    can send each statement's output to its file; None (a nested loop
    that is not the program root) leaves output undiverted. ``handed``
    and ``decisions`` are the line's hand-off and its ledger, for a
    background job to borrow. ``sink`` takes each statement's output as
    it finishes, in the order it was written, instead of the result.
    The outermost program of a session's line routes what a statement
    wrote to the session's terminal through a copy (``exec 3>&1``); a
    nested one (``eval``, ``source``) leaves that to it.
    """
    # Every program loop is one parse, which is the unit bash's alias
    # rule counts in: an alias defined on this parse and row is not
    # expanded by a use on the same parse and row. Restored on the way
    # out so a nested parse (`eval`, `source`, `bash -c`) does not leave
    # its id on the enclosing one.
    session._parse_seq += 1
    outer_parse = session._parse_current
    session._parse_current = session._parse_seq
    root = not session._line_open
    session._line_open = True
    try:
        return await _run_program(
            recurse,
            node,
            session,
            stdin,
            call_stack,
            job_table,
            agent_id,
            dispatch,
            handed,
            decisions,
            sink,
            session.terminal if root else None,
        )
    finally:
        session._parse_current = outer_parse
        if root:
            session._line_open = False


async def _run_program(
    recurse,
    node,
    session,
    stdin,
    call_stack,
    job_table,
    agent_id,
    dispatch=None,
    handed: HandOff | None = None,
    decisions: Decisions | None = None,
    sink: JobConsole | None = None,
    own: StreamOwner | None = None,
) -> tuple[Any, IOResult, ExecutionNode]:
    children = node.children
    all_stdout: list[Any] = []
    merged_io = IOResult()
    last_exec = ExecutionNode(command="", exit_code=0)
    # Source lines and the highest one `set -v` has already echoed.
    source_lines = get_text(node).split("\n")
    echoed_row = -1
    bound = fd0_binding(session)

    i = 0
    while i < len(children):
        child = children[i]

        if (
            not child.is_named
            or child.type == NT.ERROR
            or child.type == NT.COMMENT
        ):
            if child.type == NT.SEMI:
                i += 1
                continue
            i += 1
            continue

        # `set -n` reads without executing, so every statement after the
        # one that set it is skipped. Checking here rather than deeper
        # gives bash's one-way trip for free: a later `set +n` is itself
        # a statement, so it never runs and cannot turn execution back
        # on within the same input.
        if session.shell_options.get("noexec"):
            break

        # `set -v` echoes input to stderr as the reader consumes it, and
        # the unit is a *line*, not a statement: GNU answers
        # `set -v; echo a` with nothing at all, because that whole line
        # was already read before the option took effect, while
        # `set -v\necho a` echoes the second line. So a line is echoed
        # once, when the first statement on it runs, and a statement
        # spanning several lines carries all of them.
        if child.start_point[0] > echoed_row:
            # From the line after the last one echoed, not from this
            # statement's own row: the reader consumes comments and
            # blank lines too, so `# note`, an empty line and `echo ok`
            # all reach stderr. Clamping to the next executable row
            # dropped everything that carried no node.
            first = echoed_row + 1
            last = child.end_point[0]
            if session.shell_options.get("verbose") and last >= first:
                text = "\n".join(source_lines[first : last + 1])
                merged_io = await merged_io.merge(
                    IOResult(stderr=text.encode() + b"\n")
                )
            # Marked read either way: a line reaches the reader once, so
            # a line whose own first statement turned the option on was
            # already past it and is never echoed.
            echoed_row = last

        # Check for background: named node followed by & token
        is_bg = i + 1 < len(children) and children[i + 1].type == NT.BACKGROUND

        if is_bg:
            try:
                stdout, io, last_exec = await handle_background(
                    recurse,
                    child,
                    None,
                    session,
                    job_table,
                    agent_id,
                    stdin,
                    call_stack,
                    handed,
                    decisions,
                )
            except ExitSignal as sig:
                # A job the shell cannot fork ends the line, as a failed
                # fork(2) ends bash's.
                merged_io = await merged_io.merge(
                    IOResult(
                        exit_code=sig.exit_code, stderr=sig.stderr or None
                    )
                )
                merged_io.exit_code = sig.exit_code
                record_status(session, sig.exit_code)
                last_exec = ExecutionNode(
                    command=get_text(child),
                    exit_code=sig.exit_code,
                    stderr=sig.stderr,
                )
                break
            # Launching a job is itself a statement: bash sets $? to 0
            # (the launch status), so `false; cmd & echo $?` prints 0.
            record_status(session, io.exit_code)
            i += 2
        else:
            # `exec < file` feeds the shell's stdin: a later `read` or
            # `while read` sees it, and each statement reads on from
            # where the one before it stopped.
            child_stdin = statement_stdin(session, stdin, bound)
            # Each statement writes to a recorder rather than straight
            # to the program's output, so what it wrote to the terminal
            # through a copy (`exec 3>&1`) keeps its place, past an
            # `exec` diversion, and what it wrote to an enclosing level's
            # stream goes on there.
            recorder = Recorder()
            enclosing = ENCLOSING.set(recorder)
            try:
                stdout, io, last_exec = await recurse(
                    child, session, child_stdin, call_stack, sink=recorder
                )
            except UNWINDING as sig:
                if isinstance(sig, ReturnSignal) and session.source_depth <= 0:
                    raise
                merged_io = await land(
                    await statement_output(
                        recorder, None, IOResult(), own, sink
                    ),
                    sink,
                    all_stdout,
                    merged_io,
                )
                if sig.stdout:
                    all_stdout.append(sig.stdout)
                if isinstance(sig, ExitSignal):
                    # exit (or a fatal expansion error) ends the line:
                    # keep what earlier statements produced, drop the
                    # rest.
                    merged_io = await merged_io.merge(
                        IOResult(
                            exit_code=sig.exit_code, stderr=sig.stderr or None
                        )
                    )
                    last_exec = ExecutionNode(
                        command="exit",
                        exit_code=sig.exit_code,
                        stderr=sig.stderr,
                    )
                elif isinstance(sig, ReturnSignal):
                    # `return` inside a sourced file ends the source; the
                    # file's status becomes the return's. Anywhere else
                    # the signal belongs to an enclosing function call.
                    if sig.stderr:
                        merged_io = await merged_io.merge(
                            IOResult(stderr=sig.stderr)
                        )
                    last_exec = ExecutionNode(
                        command="return", exit_code=sig.exit_code
                    )
                else:
                    # break/continue with a level beyond the loop nesting
                    # ends every enclosing loop and execution continues
                    # with the next statement, like bash (which clamps
                    # the level to the actual depth).
                    merged_io = await merged_io.merge(sig.io)
                    record_status(session, sig.io.exit_code)
                    i += 1
                    continue
                merged_io.exit_code = sig.exit_code
                record_status(session, sig.exit_code)
                break
            finally:
                ENCLOSING.reset(enclosing)
            # Materialize stdout so lazy exit codes (e.g. from
            # exit_on_empty in grep) are finalized before $? is set.
            try:
                stdout = await materialize(stdout)
            except OSError as exc:
                # Lazy reads (head/tail opening the stream mid-pipeline) can
                # fail on the first pull, which is the command's failure.
                await failed_read(io, exc, last_exec)
                stdout = None
            except Exception as exc:
                existing = await materialize(io.stderr) or b""
                io.stderr = existing + f"{exc}\n".encode()
                io.exit_code = 1
                stdout = None
            record_status(
                session, io.exit_code, transparent=pipeline_transparent(child)
            )
            i += 1
            # An `exec` redirect sends the shell's own output to a file:
            # every statement after the `exec` diverts here, so nothing
            # bubbles to the terminal and stderr lands in its own target.
            written = await divert_statement(
                dispatch,
                session,
                await statement_output(recorder, stdout, io, own, sink),
                io,
                child,
                last_exec.command or "",
            )
            stdout = None
            merged_io = await land(written, sink, all_stdout, merged_io)
        if stdout is not None:
            all_stdout.append(stdout)
        merged_io = await merged_io.merge(io)

        if (
            io.exit_code != 0
            and session.shell_options.get("errexit")
            and not is_bg
            and child.type not in ERREXIT_EXEMPT_TYPES
            and not session.errexit_immune
        ):
            merged_io.exit_code = io.exit_code
            break

    if len(all_stdout) == 1:
        return all_stdout[0], merged_io, last_exec
    combined = async_chain(all_stdout) if all_stdout else None
    return combined, merged_io, last_exec
