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


async def run_cli(
    executable: str, hint: str, args: list[str], stdin: bytes | None
) -> tuple[bytes, bytes, int]:
    """One sandbox CLI invocation: its output and its exit status.

    A cancelled call kills the child before it re-raises, so a line
    abandoned to a timeout does not leave the CLI running behind it.

    Args:
        executable (str): the CLI to run (``docker``, ``smolvm``, ...).
        hint (str): the message a missing CLI raises, saying how to get it.
        args (list[str]): arguments after the executable.
        stdin (bytes | None): input for the command, or None for none.

    Raises:
        RuntimeError: the CLI is not installed.
    """
    try:
        process = await asyncio.create_subprocess_exec(
            executable,
            *args,
            stdin=(
                asyncio.subprocess.PIPE
                if stdin is not None
                else asyncio.subprocess.DEVNULL
            ),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        raise RuntimeError(hint) from None
    try:
        stdout, stderr = await process.communicate(stdin)
    except asyncio.CancelledError:
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise
    code = process.returncode if process.returncode is not None else 1
    return stdout, stderr, code
