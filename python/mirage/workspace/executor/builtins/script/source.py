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

from collections.abc import Callable
from typing import Any

from mirage.io import IOResult
from mirage.io.types import ByteSource
from mirage.runtime.types import DispatchFn
from mirage.shell.call_stack import CallStack
from mirage.types import PathSpec, word_text
from mirage.utils.errors import FS_ERRORS, fs_strerror
from mirage.workspace.executor.builtins.scope import _scope_path
from mirage.workspace.executor.builtins.script.constants import SOURCE_USAGE
from mirage.workspace.executor.builtins.script.script import (read_script_text,
                                                              script_error)
from mirage.workspace.executor.builtins.types import BuiltinCall, Result
from mirage.workspace.session import SessionState
from mirage.workspace.session.state import (positional_params,
                                            set_positional_params)
from mirage.workspace.types import ExecutionNode


async def handle_source(
    dispatch: DispatchFn,
    execute_fn: Callable[..., Any],
    path: str | PathSpec,
    session: SessionState,
    args: list[str] | None = None,
    call_stack: CallStack | None = None,
) -> tuple[ByteSource | None, IOResult, ExecutionNode]:
    """Read a script file and execute it in the calling shell.

    Unlike a nested shell, a sourced file *is* the caller, so whatever
    it sets stays set: `source f` where f runs `set -x` leaves the
    caller tracing. Only the positional parameters come back, because
    bash restores those and nothing else.

    Args:
        dispatch (DispatchFn): op dispatcher, used to read the file.
        execute_fn (Callable): runs the script text in this session.
        path (str | PathSpec): the script to source.
        session (SessionState): shell session state.
        args (list[str] | None): positional parameters to expose to the
            script. When given they replace ``$1..$#`` for the duration
            of the source and are restored afterwards, matching bash;
            when omitted the parameters in scope are the script's, and
            a ``shift`` or ``set --`` in it changes them.
        call_stack (CallStack | None): function-call scope, if any; a
            file sourced inside a function sees the function's
            parameters.
    """
    raw = _scope_path(path)
    if word_text(path) == "":
        # The empty name is a filename bash tries to open, not a missing
        # argument, so it fails like any file that is not there.
        return script_error("source",
                            ": No such file or directory",
                            1,
                            command="source ")
    try:
        script = await read_script_text(dispatch, raw, session.cwd)
    except FS_ERRORS as exc:
        return script_error("source",
                            f"{raw}: {fs_strerror(exc)}",
                            1,
                            command=f"source {raw}")
    # The file runs as a line of its own, which reads the shell's
    # parameters, so the ones in scope stand in for them while it runs.
    shell_params = session.positional_args
    session.positional_args = args or positional_params(session, call_stack)
    session.source_depth += 1
    try:
        io = await execute_fn(script, session_id=session.session_id)
    finally:
        session.source_depth -= 1
        scoped = session.positional_args
        session.positional_args = shell_params
        if not args:
            set_positional_params(session, call_stack, scoped)
    return io.stdout, io, ExecutionNode(command=f"source {raw}",
                                        exit_code=io.exit_code)


async def source_builtin(call: BuiltinCall) -> Result:
    """The ``source`` / ``.`` arm.

    Positional parameters keep the words as typed, so a path operand
    contributes its spelling, not its resolved mount path.

    Args:
        call (BuiltinCall): the invocation.
    """
    operands = list(call.argv.operands)
    if not operands:
        return script_error("source", SOURCE_USAGE, 2)
    return await handle_source(call.dispatch, call.execute_fn, operands[0],
                               call.session,
                               [word_text(o)
                                for o in operands[1:]], call.call_stack)
