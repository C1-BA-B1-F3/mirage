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
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from mirage.commands.errors import CommandTimeoutError
from mirage.io import IOResult
from mirage.io.async_line_iterator import SharedInput
from mirage.io.stream import close_quietly
from mirage.io.types import ByteSource
from mirage.ops.types import SessionView
from mirage.policy.decisions import Decisions
from mirage.policy.types import HandOff
from mirage.process.types import ProcessView
from mirage.shell.call_stack import CallStack
from mirage.shell.console import Channel, JobConsole
from mirage.shell.console.pipe import PipeConsole
from mirage.shell.constants import FORK_FAILED, FORK_FAILED_STATUS
from mirage.shell.errors import ExitSignal, ReturnSignal
from mirage.shell.helpers import get_text, is_backgrounded
from mirage.shell.job_table import Job, JobStatus, JobTable
from mirage.shell.types import TSNodeLike
from mirage.workspace.executor.builtins.getopt import scan_options
from mirage.workspace.executor.statement import statement_stdin
from mirage.workspace.node.occurrence import occurrence_of
from mirage.workspace.session import (SessionState, reset_current_session,
                                      set_current_session)
from mirage.workspace.types import ExecutionNode


async def pump(console: JobConsole, channel: Channel,
               stream: ByteSource | None) -> None:
    """Send a command's output to a console as chunks arrive.

    Consuming the stream piece by piece rather than materializing it
    whole is what lets a reader watch a running job. A command that
    computes its output eagerly still lands in one chunk, because there
    was nothing to observe before it finished. A pipe is drained before
    the next chunk is pulled, so a reader that closed stops the source
    before it fetches more.

    Args:
        console (JobConsole): where the output goes.
        channel (Channel): which stream the bytes belong to.
        stream (ByteSource | None): the output to drain.
    """
    if stream is None:
        return
    if isinstance(stream, bytes):
        if stream:
            await console.emit(channel, stream)
        return
    async for chunk in stream:
        if chunk:
            await console.emit(channel, chunk)
        if not isinstance(console, PipeConsole):
            continue
        await console.drain()
        if console.closed_reader:
            await close_quietly(stream)
            return


async def handle_background(
    execute_node,
    left: TSNodeLike,
    right: TSNodeLike | None,
    session: SessionState,
    job_table: JobTable,
    agent_id: str | None,
    stdin: ByteSource | None = None,
    call_stack=None,
    handed: HandOff | None = None,
    decisions: Decisions | None = None,
) -> tuple[ByteSource | None, IOResult, ExecutionNode]:
    """Run left side in background.

    ``handed`` and ``decisions`` are the line's hand-off and the ledger
    it lives in. The claims the line's pass made for the commands inside
    the job are copied onto one of the job's own before the job starts
    (``Decisions.split``): its gates run after the line has returned,
    and its grants have to stay reserved through the line's end
    whichever way the line ends, a release for a question left waiting
    included, and through the launch of the same job again by a loop.
    The job's whole subtree runs on that hand-off, the lines it
    evaluates included (the walker binds it into their door), and the
    job revokes it when it ends, which spends what no other hand-off
    still holds.
    """
    bg_session = session.fork()
    bg_call_stack = call_stack.fork() if call_stack is not None else None
    job_handed = (decisions.split(session.session_id, handed,
                                  occurrence_of(left, handed))
                  if handed is not None and decisions is not None else None)

    async def _run_bg(job: Job) -> tuple[IOResult, ExecutionNode]:
        # Background jobs don't receive stdin, matching real shell
        # behavior where bg processes get /dev/null. This prevents
        # race conditions when stdin is an async iterator.
        console = job.console
        cmd_str_inner = get_text(left) if hasattr(left, "text") else str(left)
        # The task's context snapshot still points at the OUTER session
        # (create_task copies the context before the fork can be bound),
        # and the fork keeps its parent's id, so without this rebind a
        # nested eval inside the job resolves the ambient outer session
        # and escapes the fork.
        token = set_current_session(bg_session)
        try:
            try:
                # Handing the console down as a sink is what makes
                # compound bodies stream: each statement writes as it
                # finishes rather than the whole construct landing at
                # the end. Statements that emit return no stdout, so the
                # pump below is a no-op for them and still covers
                # constructs that do not stream.
                # A job outlives the line that launched it and is not the
                # caller's to abort, as bash leaves a background job alone
                # on SIGINT and a TypeScript job runs under its own
                # controller: it runs without the line's event.
                stdout, io, exec_node = await execute_node(left,
                                                           bg_session,
                                                           None,
                                                           bg_call_stack,
                                                           sink=console,
                                                           handed=job_handed,
                                                           cancel=None)
            except CommandTimeoutError as exc:
                msg = (str(exc) + "\n").encode()
                stdout = b""
                io = IOResult(exit_code=124, stderr=msg)
                exec_node = ExecutionNode(command=cmd_str_inner,
                                          stderr=msg,
                                          exit_code=124)
            except ExitSignal as sig:
                # A background job is its own shell: exit ends the job
                # only.
                stdout = sig.stdout or b""
                io = IOResult(exit_code=sig.contained_code,
                              stderr=sig.stderr or None)
                exec_node = ExecutionNode(command=cmd_str_inner,
                                          stderr=sig.stderr,
                                          exit_code=sig.contained_code)
            except ReturnSignal as sig:
                stdout = None
                io = IOResult(exit_code=sig.exit_code,
                              stderr=sig.stderr or None)
                exec_node = ExecutionNode(command=cmd_str_inner,
                                          stderr=sig.stderr,
                                          exit_code=sig.exit_code)
            # Drain inside the rebind: pumping the stream can still run
            # ops that read the ambient session.
            await pump(console, Channel.STDOUT, stdout)
            stderr = await io.materialize_stderr()
            if stderr:
                await console.emit(Channel.STDERR, stderr)
            return io, exec_node
        finally:
            reset_current_session(token)
            if job_handed is not None and decisions is not None:
                await decisions.revoke(session.session_id, job_handed)

    cmd_str = get_text(left) if hasattr(left, 'text') else str(left)

    # Non-interactive bash announces nothing on launch ("[1] <pid>" is
    # interactive-only); the job stays discoverable via $! and `jobs`.
    try:
        job = job_table.submit(command=cmd_str,
                               run=_run_bg,
                               cwd=bg_session.cwd,
                               agent=agent_id or "",
                               session_id=session.session_id,
                               parent_pid=session.process_id,
                               limit=session.processes.max)
    except Exception as exc:
        # A submission that fails (a console the table cannot build, a
        # session at its process cap) starts no runner, so nothing would
        # ever revoke the job's hand-off: its grants would stay reserved
        # for good, neither spent nor on offer to any later line.
        if job_handed is not None and decisions is not None:
            await decisions.revoke(session.session_id, job_handed)
        if isinstance(exc, BlockingIOError):
            raise ExitSignal(FORK_FAILED_STATUS, stderr=FORK_FAILED) from exc
        raise
    bg_session.process_id = (job.process.info.pid
                             if job.process is not None else None)
    session.last_bg_job_id = job.pid

    if right is None:
        return None, IOResult(), ExecutionNode(
            op="&",
            exit_code=0,
            children=[ExecutionNode(command=cmd_str, exit_code=0)])

    right_stdout, right_io, right_exec = await execute_node(
        right, session, stdin, call_stack)
    children = [
        ExecutionNode(command=cmd_str, exit_code=0),
        right_exec,
    ]
    return right_stdout, right_io, ExecutionNode(op="&",
                                                 exit_code=right_io.exit_code,
                                                 children=children)


async def run_statement(
    execute_node: Callable[..., Any],
    node: TSNodeLike,
    session: SessionState,
    stdin: ByteSource | None,
    bound: tuple[SharedInput | None, bool],
    call_stack: CallStack | None,
    job_table: JobTable | None,
    agent_id: str | None,
    handed: HandOff | None = None,
    decisions: Decisions | None = None,
) -> tuple[ByteSource | None, IOResult, ExecutionNode]:
    """Run one statement of a compound body, as a job when it ends in ``&``.

    The program loop and the subshell body read the ``&`` off the token
    stream themselves; a loop body, an if/case arm, a brace group or a
    function body holds named nodes only, so the statement is asked
    about its own terminator. The launch is a statement in its own
    right and answers with status 0, as in bash, so ``false &`` inside
    a body trips neither ``$?`` nor ``set -e``.

    Args:
        execute_node (Callable): the executor's statement runner.
        node (TSNodeLike): the statement.
        session (SessionState): shell session.
        stdin (ByteSource | None): the body's input; a job gets none,
            like a background process reading /dev/null.
        bound (tuple[SharedInput | None, bool]): ``fd0_binding`` as the
            body started, so an ``exec <`` in it replaces ``stdin``.
        call_stack (CallStack | None): function-call scope, if any.
        job_table (JobTable | None): where the job lives. None means
            the caller wired no job plane, which is a programming
            error once a ``&`` shows up, not a reason to run inline.
        agent_id (str | None): agent identity for job bookkeeping.
        handed (HandOff | None): approval claims inherited by a job.
        decisions (Decisions | None): ledger that holds those claims.
    """
    if not is_backgrounded(node):
        return await execute_node(node, session,
                                  statement_stdin(session, stdin, bound),
                                  call_stack)
    if job_table is None:
        raise RuntimeError(
            f"`{get_text(node)} &` needs a job table; none was wired")
    return await handle_background(execute_node, node, None, session,
                                   job_table, agent_id, stdin, call_stack,
                                   handed, decisions)


_WAIT_USAGE = "wait: usage: wait [-fn] [-p var] [id ...]"
_DISOWN_USAGE = "disown: usage: disown [-h] [-ar] [jobspec ... | pid ...]"
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _job_result(
        cmd_str: str, msg: str,
        code: int) -> tuple[ByteSource | None, IOResult, ExecutionNode]:
    err = msg.encode()
    return None, IOResult(exit_code=code,
                          stderr=err), ExecutionNode(command=cmd_str,
                                                     exit_code=code,
                                                     stderr=err)


def _session_of(session: SessionState | None) -> str:
    """The job list a builtin reads: the calling session's, or the shared
    empty id when it runs with no session (a bare table in a test).

    Args:
        session (SessionState | None): the shell session, if any.
    """
    return session.session_id if session is not None else ""


def _process_view(job_table: JobTable,
                  session: SessionState | None) -> ProcessView:
    """The managed runners `ps` and numeric `kill` reach, scoped by the
    session's profile.

    Args:
        job_table (JobTable): the workspace's job table.
        session (SessionState | None): the shell session, if any.
    """
    if session is None:
        return job_table.processes.view("")
    return job_table.processes.view(session.session_id,
                                    lambda: session.processes)


def _job_numbered(jobs: list[Job], job_id: int) -> Job | None:
    """The job whose number is `job_id`, the one `%N` names.

    Args:
        jobs (list[Job]): the jobs the builtin can see.
        job_id (int): the job number.
    """
    return next((j for j in jobs if j.id == job_id), None)


def _resolve_spec(jobs: list[Job], spec: str) -> tuple[Job | None, str]:
    """The job a `wait`/`disown` operand names, or bash's refusal.

    A `%N` spec that names no job is `no such job`; a bare number is a
    managed PID, also returned by `$!`, so a bare number that names no
    job is bash's `pid N is not a child of this shell`. Anything else
    is `not a pid or valid job spec`.

    Args:
        jobs (list[Job]): the jobs the builtin can see.
        spec (str): the operand as typed.
    """
    if spec.startswith("%"):
        raw = spec[1:]
        job = _job_numbered(jobs, int(raw)) if raw.isdigit() else None
        return job, "" if job is not None else f"{spec}: no such job"
    if spec.isdigit():
        job = next((j for j in jobs if j.pid == int(spec)), None)
        return job, "" if job is not None else (
            f"pid {spec} is not a child of this shell")
    return None, f"`{spec}': not a pid or valid job spec"


async def _wait_first(job_table: JobTable, jobs: list[Job]) -> Job:
    """Block until the first of several jobs ends, and return it.

    Args:
        job_table (JobTable): the session's jobs.
        jobs (list[Job]): the candidates, all present in the table.
    """
    for job in jobs:
        if job.status != JobStatus.RUNNING:
            return await job_table.wait(job.id, job.session_id)
    tasks = {
        asyncio.ensure_future(job_table.wait(job.id, job.session_id)): job
        for job in jobs
    }
    done, pending = await asyncio.wait(tasks,
                                       return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    first = min(done, key=lambda t: tasks[t].id)
    return tasks[first]


async def _adopt(
        job_table: JobTable, job: Job,
        cmd_str: str) -> tuple[ByteSource | None, IOResult, ExecutionNode]:
    """Report one finished job's output and status, and reap it.

    Args:
        job_table (JobTable): the session's jobs.
        job (Job): the job, already finished.
        cmd_str (str): the command line, for the node.
    """
    stdout = await job.console.snapshot(Channel.STDOUT)
    stderr = await job.console.snapshot(Channel.STDERR)
    # Reaped like GNU bash reaps a job waited on by id, so a later bare
    # `wait` does not adopt this console a second time.
    job_table.reap(job.id, job.session_id)
    return stdout, IOResult(
        exit_code=job.exit_code,
        stderr=stderr or None,
    ), ExecutionNode(command=cmd_str, exit_code=job.exit_code)


async def handle_wait(
    job_table: JobTable,
    parts: list[str],
    session: SessionState | None = None,
    view: SessionView | None = None,
) -> tuple[ByteSource | None, IOResult, ExecutionNode]:
    """Wait for background jobs, with bash's option surface.

    Bare `wait` joins every job and adopts each one's output in id
    order (a real shell has nothing to adopt; mirage jobs print to
    their console, so the shell has to surface it or it is stranded);
    `wait ID...` joins those and answers the last one's status; `-n`
    joins the first of the given jobs (or of all) to finish and answers
    its status, 127 when there is nothing to wait for; `-p VAR` stores
    the id of the job whose status is answered, and unsets VAR when
    none is (which is the bare form, since it reports no one job);
    `-f` is accepted, since a mirage job cannot stop, only end.

    `-p` stores the managed PID, matching `$!` and `jobs -p`.
    A spec naming no job is bash's own message and 127; a word that is
    neither is `not a pid or valid job spec` and 1.

    Args:
        job_table (JobTable): the session's jobs.
        parts (list[str]): the command words, `wait` first.
        session (SessionState | None): shell session state, for `-p`.
        view (SessionView | None): the session plane's gated door.
    """
    cmd_str = " ".join(parts)
    sid = _session_of(session)
    next_job = False
    var: str | None = None
    specs: list[str] = []
    i = 1
    while i < len(parts):
        word = parts[i]
        if specs or not word.startswith("-") or word == "-":
            specs.append(word)
            i += 1
            continue
        if word == "--":
            specs.extend(parts[i + 1:])
            break
        j = 1
        while j < len(word):
            ch = word[j]
            if ch == "n":
                next_job = True
            elif ch == "f":
                pass
            elif ch == "p":
                rest = word[j + 1:]
                if rest:
                    var = rest
                elif i + 1 < len(parts):
                    i += 1
                    var = parts[i]
                else:
                    return _job_result(
                        cmd_str, f"bash: wait: -p: option requires an "
                        f"argument\n{_WAIT_USAGE}\n", 2)
                break
            else:
                return _job_result(
                    cmd_str,
                    f"bash: wait: -{ch}: invalid option\n{_WAIT_USAGE}\n", 2)
            j += 1
        i += 1
    if var is not None:
        if _IDENTIFIER.fullmatch(var) is None:
            return _job_result(
                cmd_str, f"bash: wait: `{var}': not a valid identifier\n", 1)
        if view is not None and view.is_readonly(var):
            return _job_result(
                cmd_str,
                f"bash: wait: {var}: cannot unset: readonly variable\n", 1)
        if view is not None:
            await view.unset(var)
    errors: list[str] = []
    picked: list[Job] = []
    visible = job_table.list_jobs(sid)
    for spec in specs:
        job, refusal = _resolve_spec(visible, spec)
        if job is None:
            errors.append(f"bash: wait: {refusal}")
            continue
        picked.append(job)
    err_text = ("\n".join(errors) + "\n") if errors else ""
    if next_job:
        candidates = picked if specs else visible
        if not candidates:
            # Nothing to wait for: the specs were all bad, or there are
            # no jobs. bash reports any bad spec and answers 127.
            code = 127
            return None, IOResult(exit_code=code,
                                  stderr=err_text.encode()
                                  or None), ExecutionNode(command=cmd_str,
                                                          exit_code=code)
        job = await _wait_first(job_table, candidates)
        if var is not None and view is not None:
            await view.set(var, str(job.pid))
        stdout, io, node = await _adopt(job_table, job, cmd_str)
        if err_text:
            prior = io.stderr if isinstance(io.stderr, bytes) else b""
            io.stderr = err_text.encode() + prior
        return stdout, io, node
    if not specs:
        # Every unreaped job, not just the ones still running: a job
        # that finished before this line was reached has output nobody
        # has read, and whether it finished in time is a scheduling
        # accident. Ordered by job id, because jobs finish concurrently
        # and completion order is not reproducible. Reaped afterwards so
        # a second `wait` does not print the same output twice.
        await job_table.wait_all(sid)
        out = b""
        err = b""
        for finished in sorted(job_table.list_jobs(sid), key=lambda j: j.id):
            out += await finished.console.snapshot(Channel.STDOUT)
            err += await finished.console.snapshot(Channel.STDERR)
        job_table.pop_completed(sid)
        return out or None, IOResult(stderr=err or None), ExecutionNode(
            command=cmd_str, exit_code=0)
    if not picked:
        # Every spec was refused: bash answers 127 for a job it cannot
        # find and 1 for a word that is not a spec at all, the last
        # refusal deciding.
        last = errors[-1]
        code = 1 if last.endswith("not a pid or valid job spec") else 127
        return _job_result(cmd_str, err_text, code)
    outs: list[bytes] = []
    errs: list[bytes] = [err_text.encode()] if err_text else []
    last_code = 0
    last_job: Job | None = None
    for job in picked:
        finished = await job_table.wait(job.id, sid)
        stdout, io, _ = await _adopt(job_table, finished, cmd_str)
        if stdout:
            outs.append(stdout if isinstance(stdout, bytes) else b"")
        if io.stderr:
            errs.append(io.stderr if isinstance(io.stderr, bytes) else b"")
        last_code = io.exit_code
        last_job = finished
    # `wait id1 id2` answers with the last id's status, so `-p` names
    # that same job however many were waited for. Only the no-operand
    # form leaves the variable unset, since it reports no one job.
    if var is not None and view is not None and last_job is not None:
        await view.set(var, str(last_job.pid))
    return b"".join(outs) or None, IOResult(exit_code=last_code,
                                            stderr=b"".join(errs)
                                            or None), ExecutionNode(
                                                command=cmd_str,
                                                exit_code=last_code)


async def handle_disown(
    job_table: JobTable,
    parts: list[str],
    session: SessionState | None = None,
    view: SessionView | None = None,
) -> tuple[ByteSource | None, IOResult, ExecutionNode]:
    """Drop jobs from the table without stopping them.

    bash's grammar: no operand means the current job (the newest), `-a`
    every job, `-r` the running ones, and `%N`/`N` specs name jobs; `-h`
    marks a job to survive SIGHUP and otherwise leaves it in the table,
    which is a no-op here since no hangup is ever delivered. A spec that
    names no job is `no such job`, exit 1, and the others still drop.

    Args:
        job_table (JobTable): the session's jobs.
        parts (list[str]): the command words, `disown` first.
        session (SessionState | None): the shell session, whose profile
            decides which jobs are visible.
        view (SessionView | None): unused; the job-builtin signature.
    """
    cmd_str = " ".join(parts)
    sid = _session_of(session)
    scan = scan_options(parts[1:], "arh")
    if scan.bad is not None:
        return _job_result(
            cmd_str,
            f"bash: disown: {scan.bad}: invalid option\n{_DISOWN_USAGE}\n", 2)
    all_jobs = "a" in scan.letters
    running_only = "r" in scan.letters
    keep = "h" in scan.letters
    specs = scan.operands
    targets: list[Job] = []
    errors: list[str] = []
    jobs = job_table.list_jobs(sid)
    if specs:
        for spec in specs:
            job, _ = _resolve_spec(jobs, spec)
            if job is None:
                errors.append(f"bash: disown: {spec}: no such job")
                continue
            targets.append(job)
    elif all_jobs or running_only:
        targets = ([j for j in jobs if j.status == JobStatus.RUNNING]
                   if running_only else jobs)
    else:
        if not jobs:
            return _job_result(cmd_str, "bash: disown: current: no such job\n",
                               1)
        targets = [jobs[-1]]
    if not keep:
        for job in targets:
            job_table.disown(job.id, sid)
    err = ("\n".join(errors) + "\n").encode() if errors else None
    code = 1 if errors else 0
    return None, IOResult(exit_code=code,
                          stderr=err), ExecutionNode(command=cmd_str,
                                                     exit_code=code,
                                                     stderr=err or b"")


async def handle_fg(
    job_table: JobTable,
    parts: list[str],
    session: SessionState | None = None,
    view: SessionView | None = None,
) -> tuple[ByteSource | None, IOResult, ExecutionNode]:
    """Foreground a background job: print its command line, then block
    on it and adopt its output and exit code.

    Args:
        job_table (JobTable): the session's job table.
        parts (list[str]): argv including the command name; the
            optional operand is a job id, with or without ``%``.
        session (SessionState | None): the shell session, whose profile
            decides which jobs are visible and whether the command line
            is printed.
    """
    cmd_str = " ".join(parts)
    sid = _session_of(session)
    jobs = job_table.list_jobs(sid)
    if len(parts) <= 1:
        running = [j for j in jobs if j.status == JobStatus.RUNNING]
        if not running:
            err = b"fg: current: no such job\n"
            return None, IOResult(exit_code=1,
                                  stderr=err), ExecutionNode(command=cmd_str,
                                                             exit_code=1,
                                                             stderr=err)
        job_id = running[-1].id
    else:
        raw = parts[1].lstrip("%")
        try:
            job_id = int(raw)
        except ValueError:
            err = f"fg: {parts[1]}: no such job\n".encode()
            return None, IOResult(exit_code=1,
                                  stderr=err), ExecutionNode(command=cmd_str,
                                                             exit_code=1,
                                                             stderr=err)
        if _job_numbered(jobs, job_id) is None:
            err = f"fg: {parts[1]}: no such job\n".encode()
            return None, IOResult(exit_code=1,
                                  stderr=err), ExecutionNode(command=cmd_str,
                                                             exit_code=1,
                                                             stderr=err)
    job = await job_table.wait(job_id, sid)
    header = (job.command + "\n").encode()
    stdout = header + await job.console.snapshot(Channel.STDOUT)
    stderr = await job.console.snapshot(Channel.STDERR)
    job_table.reap(job_id, sid)
    return stdout, IOResult(
        exit_code=job.exit_code,
        stderr=stderr or None,
    ), ExecutionNode(command=cmd_str, exit_code=job.exit_code)


_KILL_SIGNALS = {"0": 0, "HUP": 1, "INT": 2, "QUIT": 3, "KILL": 9, "TERM": 15}


def _kill_args(words: list[str]) -> tuple[int, list[str]]:
    """Parse kill's signal selector without treating it as a PID.

    Managed runners support probes and cancellation, not stop/continue or
    arbitrary signal delivery. Terminating signals use the runtime's existing
    cancellation channel (and its managed cancellation status, 137).

    Args:
        words (list[str]): arguments after kill.
    """
    signal = "TERM"
    if words and words[0] in ("-s", "-n"):
        if len(words) < 2:
            raise ValueError("option requires an argument")
        signal, words = words[1], words[2:]
    elif words and words[0].startswith("-") and words[0] != "--":
        signal, words = words[0][1:], words[1:]
    if words and words[0] == "--":
        words = words[1:]
    key = signal.removeprefix("SIG")
    number = int(
        key) if key.isascii() and key.isdigit() else _KILL_SIGNALS.get(key)
    if number is None or number not in _KILL_SIGNALS.values():
        raise ValueError(f"{signal}: unsupported signal")
    if not words:
        raise ValueError(
            "usage: kill [-s sigspec | -n signum | -sigspec] pid | jobspec ..."
        )
    return number, words


async def handle_kill(
    job_table: JobTable,
    parts: list[str],
    session: SessionState | None = None,
    view: SessionView | None = None,
) -> tuple[ByteSource | None, IOResult, ExecutionNode]:
    cmd_str = " ".join(parts)
    sid = _session_of(session)
    try:
        signal, operands = _kill_args(parts[1:])
    except ValueError as exc:
        return _job_result(cmd_str, f"kill: {exc}\n", 1)
    processes = _process_view(job_table, session)
    errors: list[str] = []
    for operand in operands:
        raw = operand[1:] if operand.startswith("%") else operand
        if not raw.isascii() or not raw.isdigit() or int(raw) <= 0:
            errors.append(f"kill: invalid job id: {operand}")
            continue
        number = int(raw)
        job = (_job_numbered(job_table.list_jobs(sid), number)
               if operand.startswith("%") else next(
                   (j for j in job_table.list_jobs(sid)
                    if j.pid == number), None))
        pid = job.pid if job is not None else number
        try:
            if operand.startswith("%") and job is None:
                success = False
            elif signal == 0:
                success = processes.probe(pid)
            else:
                success = processes.terminate(pid)
                if success and job is not None:
                    await job_table.kill(job.id, sid)
        except PermissionError:
            errors.append(f"kill: ({pid}) - Operation not permitted")
            continue
        if not success:
            errors.append(f"kill: no such job: {number}")
    if errors:
        return _job_result(cmd_str, "\n".join(errors) + "\n", 1)
    return None, IOResult(), ExecutionNode(command=cmd_str, exit_code=0)


_JOBS_FLAGS = frozenset("lnprs")
_JOBS_USAGE = ("jobs: usage: jobs [-lnprs] [jobspec ...] "
               "or jobs -x command [args]")


def _job_row(job: Job, long: bool) -> str:
    """One `jobs` line in mirage's own row shape.

    Args:
        job (Job): the job.
        long (bool): `-l`, which includes the managed process id.
    """
    if long:
        return f"[{job.id}] {job.pid} {job.status.value} {job.command}"
    return f"[{job.id}] {job.status.value} {job.command}"


async def handle_jobs(
    job_table: JobTable,
    parts: list[str],
    session: SessionState | None = None,
    view: SessionView | None = None,
) -> tuple[ByteSource | None, IOResult, ExecutionNode]:
    """List jobs, with bash's flags applied to mirage's row shape.

    `-p` prints the managed PID; `-s` lists nothing because suspended
    processes are unsupported. `-r` keeps running jobs, `-l` adds the PID, and
    `-n` lists only the jobs whose status changed since the last `jobs`
    (which is every completed one not yet reaped, since reaping is what
    a listing does). A jobspec operand (`%2` or `2`) filters to that
    job; one that names no job is `no such job`, exit 1. `-x` is not
    carried, and an unknown letter is GNU's usage line, exit 2.

    Args:
        job_table (JobTable): the session's jobs.
        parts (list[str]): the command words, `jobs` first.
    """
    cmd_str = " ".join(parts)
    sid = _session_of(session)
    flags: set[str] = set()
    specs: list[str] = []
    for word in parts[1:]:
        if word.startswith("-") and len(word) > 1 and not specs:
            if word == "--":
                continue
            bad = next((c for c in word[1:] if c not in _JOBS_FLAGS), None)
            if bad is not None:
                err = (f"bash: jobs: -{bad}: invalid option\n"
                       f"{_JOBS_USAGE}\n").encode()
                return None, IOResult(exit_code=2, stderr=err), ExecutionNode(
                    command=cmd_str, exit_code=2, stderr=err)
            flags.update(word[1:])
        else:
            specs.append(word)
    jobs = job_table.list_jobs(sid)
    if specs:
        picked: list[Job] = []
        for spec in specs:
            raw = spec.lstrip("%")
            job = _job_numbered(jobs, int(raw)) if raw.isdigit() else None
            if job is None:
                err = f"bash: jobs: {spec}: no such job\n".encode()
                return None, IOResult(exit_code=1, stderr=err), ExecutionNode(
                    command=cmd_str, exit_code=1, stderr=err)
            picked.append(job)
        jobs = picked
    if "r" in flags:
        jobs = [j for j in jobs if j.status == JobStatus.RUNNING]
    if "s" in flags:
        jobs = []
    if "n" in flags:
        jobs = [j for j in jobs if j.status != JobStatus.RUNNING]
    if "p" in flags:
        lines = [str(j.pid) for j in jobs]
    else:
        lines = [_job_row(j, "l" in flags) for j in jobs]
    job_table.pop_completed(sid)
    out = ("\n".join(lines) + "\n").encode() if lines else b""
    return out, IOResult(), ExecutionNode(command=cmd_str, exit_code=0)


_PS_HEADERS = {
    "pid": "PID",
    "ppid": "PPID",
    "cmd": "CMD",
    "args": "COMMAND",
    "comm": "COMMAND"
}


@dataclass(frozen=True, slots=True)
class PsOptions:
    pids: frozenset[int]
    all: bool
    columns: tuple[tuple[str, str], ...]


def _parse_ps(words: list[str]) -> PsOptions:
    """Parse procps selection and repeated output lists for managed processes.

    Args:
        words (list[str]): arguments after ps.
    """
    pids: set[int] = set()
    columns: list[tuple[str, str]] = []
    all_processes = False
    at = 0
    while at < len(words):
        word = words[at]
        at += 1
        if word == "aux":
            all_processes = True
            continue
        if word.startswith("--"):
            option, _, attached = word.partition("=")
            if option == "--pid":
                letters = "p"
            elif option == "--format":
                letters = "o"
            else:
                raise ValueError(f"unsupported option: {word}")
        elif word.startswith("-"):
            letters, attached = word[1:], ""
        else:
            raise ValueError(f"unsupported option: {word}")
        while letters:
            flag, letters = letters[0], letters[1:]
            if flag in "eAax":
                all_processes = True
                continue
            if flag in "fu":
                continue
            if flag not in "po":
                raise ValueError(f"unsupported option: -{flag}")
            value = attached or letters
            letters = ""
            if not value:
                if at == len(words):
                    raise ValueError(f"option -{flag} requires an argument")
                value = words[at]
                at += 1
            if flag == "p":
                tokens = value.replace(",", " ").split()
                if not tokens or any(
                        not t.isascii() or not t.isdigit() or int(t) <= 0
                        for t in tokens):
                    raise ValueError("process ID list syntax error")
                pids.update(int(t) for t in tokens)
            else:
                for token in value.replace(",", " ").split():
                    key, equal, header = token.partition("=")
                    if key not in _PS_HEADERS:
                        raise ValueError(
                            f"unknown output format specifier: {key}")
                    columns.append(
                        (key, header if equal else _PS_HEADERS[key]))
                if not columns:
                    raise ValueError("empty format list")
    return PsOptions(frozenset(pids), all_processes, tuple(columns))


async def handle_ps(
    job_table: JobTable,
    parts: list[str],
    session: SessionState | None = None,
    view: SessionView | None = None,
) -> tuple[ByteSource | None, IOResult, ExecutionNode]:
    cmd_str = " ".join(parts)
    try:
        options = _parse_ps(parts[1:])
    except ValueError as exc:
        return _job_result(cmd_str, f"ps: {exc}\n", 1)
    processes = [
        info for info in _process_view(job_table, session).list()
        if options.all or not options.pids or info.pid in options.pids
    ]
    lines: list[str] = []
    if options.columns:
        widths = [
            max(5 if key in ("pid", "ppid") else 0, len(header))
            for key, header in options.columns
        ]
        if any(header for _, header in options.columns):
            lines.append(" ".join(
                header.rjust(width) if key in ("pid",
                                               "ppid") else header.ljust(width)
                for (key,
                     header), width in zip(options.columns, widths)).rstrip())
        for info in processes:
            values = {
                "pid":
                str(info.pid),
                "ppid":
                str(info.parent_pid or 0),
                "cmd":
                info.command,
                "args":
                info.command,
                "comm":
                info.command.split()[0].rsplit("/", 1)[-1]
                if info.command else ""
            }
            lines.append(" ".join(
                values[key].rjust(width) if key in (
                    "pid", "ppid") else values[key].ljust(width)
                for (key, _), width in zip(options.columns, widths)).rstrip())
    else:
        # Managed runners have no CPU/RSS/TTY accounting; retain the compact
        # default view. -o provides procps columns without inventing OS facts.
        lines = [f"{info.pid}\t{info.command}" for info in processes]
    code = 0 if processes else 1
    out = ("\n".join(lines) + "\n").encode() if lines else b""
    return out, IOResult(exit_code=code), ExecutionNode(command=cmd_str,
                                                        exit_code=code)
