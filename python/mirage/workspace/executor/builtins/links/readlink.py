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

from functools import partial

from mirage.commands.builtin.generic.realpath import canonicalize
from mirage.commands.builtin.utils.paths import (
    dispatch_stat,
    dot_refusal,
    typed_spec,
)
from mirage.commands.spec.usage import missing_operand_error
from mirage.io import IOResult
from mirage.runtime.types import DispatchFn
from mirage.types import PathSpec
from mirage.workspace.executor.builtins.links.ln import operand_abs
from mirage.workspace.executor.builtins.shared import (
    fail,
    operand_text,
    split_flags,
)
from mirage.workspace.executor.builtins.types import Result
from mirage.workspace.mount.namespace import Namespace
from mirage.workspace.session import SessionState
from mirage.workspace.types import ExecutionNode


async def handle_readlink(
    namespace: Namespace,
    dispatch: DispatchFn,
    session: SessionState,
    args: list[str | PathSpec],
) -> Result:
    """Print a symlink's target, GNU readlink semantics.

    The three canonicalizing flags differ only in how much of the
    resolved path has to exist: ``-m`` requires nothing, ``-f`` requires
    every component but the last, and ``-e`` requires all of it. A path
    that falls short prints nothing and exits 1.

    Args:
        namespace (Namespace): addressing authority holding the links.
        dispatch (DispatchFn): op dispatcher, used for the existence check.
        session (SessionState): current session, for the working directory.
        args (list[str | PathSpec]): the command's words after the name.
    """
    flags, operands = split_flags(args, "fenm")
    if not operands:
        error = missing_operand_error("readlink", None)
        return fail("readlink", f"{error}\n", error.exit_code)
    # The last of -e, -f and -m wins, as in GNU readlink.
    typed = "".join(map(operand_text, args[: len(args) - len(operands)]))
    last = next((c for c in reversed(typed) if c in "efm"), None)
    mode = None if last is None else "" if last == "f" else last
    lines: list[str] = []
    exit_code = 0
    for op in operands:
        abs_op = operand_abs(namespace, op, session.cwd)
        spec = typed_spec(op, session.cwd)
        # The link entry is namespace state behind the op door: session
        # grants and admission policies decide whether this session may
        # read the target at all, so a link operand clears it even under
        # -f, -e and -m. EINVAL (not a link), a refusal and a failed walk
        # all land on GNU readlink's silent exit 1.
        try:
            if mode is not None:
                if namespace.is_link(abs_op):
                    await dispatch("readlink", PathSpec.from_str_path(abs_op))
                lines.append(
                    await canonicalize(
                        spec.raw_path,
                        session.cwd,
                        mode,
                        False,
                        namespace.readlink,
                        partial(dispatch_stat, dispatch),
                    )
                )
                continue
            if (
                spec.walk_error is not None
                or await dot_refusal(
                    partial(dispatch_stat, dispatch), spec, namespace.follow
                )
                is not None
            ):
                exit_code = 1
                continue
            target, _ = await dispatch(
                "readlink", PathSpec.from_str_path(abs_op)
            )
        except OSError:
            exit_code = 1
            continue
        lines.append(target)
    if "n" in flags:
        text = "".join(lines)
    else:
        text = "".join(line + "\n" for line in lines)
    return (
        text.encode() if text else None,
        IOResult(exit_code=exit_code),
        ExecutionNode(command="readlink", exit_code=exit_code),
    )
