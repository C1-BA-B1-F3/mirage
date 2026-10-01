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

from mirage.commands.spec.constants import ECHO_OPTION
from mirage.io import IOResult
from mirage.io.types import ByteSource
from mirage.shell.bytes import encode_text
from mirage.workspace.executor.builtins.echo.escapes import interpret_escapes
from mirage.workspace.executor.builtins.types import BuiltinCall, Result
from mirage.workspace.types import ExecutionNode


async def handle_echo(
    args: list[str],
) -> tuple[ByteSource | None, IOResult, ExecutionNode]:
    """Print arguments, honoring GNU echo's option rules.

    GNU echo is not getopt: options are LEADING words matching
    ``-[neE]+`` only. The first word that does not match (including
    ``-x`` or a repeated ``hi -n``) ends option parsing and prints
    literally. Within clusters the last of -e/-E wins; -n sticks.
    Under -e a ``\\c`` ends the output where it stands, newline
    included.

    Args:
        args (list[str]): words after the command name, as typed.
    """
    no_newline = False
    escapes = False
    idx = 0
    for word in args:
        if not ECHO_OPTION.fullmatch(word):
            break
        for ch in word[1:]:
            if ch == "n":
                no_newline = True
            elif ch == "e":
                escapes = True
            else:
                escapes = False
        idx += 1
    text = " ".join(args[idx:])
    stop = False
    if escapes:
        text, stop = interpret_escapes(text)
    if not no_newline and not stop:
        text += "\n"
    out = encode_text(text)
    return out, IOResult(), ExecutionNode(command="echo", exit_code=0)


async def echo_builtin(call: BuiltinCall) -> Result:
    """The ``echo`` arm.

    Args:
        call (BuiltinCall): the invocation.
    """
    return await handle_echo(list(call.argv.args))
