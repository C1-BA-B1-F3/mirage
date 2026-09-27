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
import json

from mirage.runtime.mixin import ProcessExecutorMixin
from mirage.runtime.sandbox.apple_container.config import AppleContainerConfig
from mirage.runtime.sandbox.apple_container.constants import (
    APPLE_CONTAINER_CLI_HINT, PRELUDE, RUNNING_STATE, not_running_hint)
from mirage.runtime.sandbox.base import RemoteSandbox
from mirage.runtime.types import ProcessExecution, RunResult


class AppleContainerRuntime(RemoteSandbox, ProcessExecutorMixin):
    """A container under Apple's `container` tool as a whole-line runtime.

    You start the container yourself; mirage only connects to it and
    execs lines. The `container` CLI is the transport, so there is no
    SDK dependency and no XPC wiring; each line is one `container exec`
    with the merged environment, the session cwd, real stdin, and
    separated stderr.

    Each container is its own lightweight VM with its own Linux
    kernel, so, as in a smolvm guest, the line sees nothing of the
    host's filesystem except what the container was given at start
    (`--volume`). Serve the workspace inside it at the host's mount
    prefixes, the same contract every provider in this family carries.
    The image needs a POSIX sh, which every argv runs under (PRELUDE).

    Args:
        options (Any): the RemoteSandbox constructor fields.
    """

    name = "apple_container"
    config_cls = AppleContainerConfig
    config: AppleContainerConfig

    async def _container(
            self,
            args: list[str],
            stdin: bytes | None = None) -> tuple[bytes, bytes, int]:
        """One container CLI invocation; the seam tests override."""
        try:
            process = await asyncio.create_subprocess_exec(
                "container",
                *args,
                stdin=(asyncio.subprocess.PIPE
                       if stdin is not None else asyncio.subprocess.DEVNULL),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            raise RuntimeError(APPLE_CONTAINER_CLI_HINT) from None
        try:
            stdout, stderr = await process.communicate(stdin)
        except asyncio.CancelledError:
            if process.returncode is None:
                process.kill()
            await process.wait()
            raise
        code = process.returncode if process.returncode is not None else 1
        return stdout, stderr, code

    async def connect(self) -> None:
        """Probe the container, refusing any state that cannot take a line.

        `container exec` refuses a container that is not running as
        well; probing once up front names the state and how to recover.
        """
        stdout, stderr, code = await self._container(
            ["inspect", self.config.container])
        if code != 0:
            raise RuntimeError(
                f"container inspect failed: {stderr.decode().strip()}")
        try:
            state = json.loads(stdout)[0]["status"]["state"]
        except (ValueError, LookupError, TypeError) as exc:
            raise RuntimeError("container inspect returned unreadable "
                               f"json: {exc}") from exc
        if state != RUNNING_STATE:
            raise RuntimeError(
                not_running_hint(self.config.container, str(state)))

    async def exec_line(self, line: str, stdin: bytes | None,
                        env: dict[str, str], cwd: str) -> RunResult:
        return await self._exec_argv(("sh", "-c", line), stdin, env, cwd)

    async def run_process(self, request: ProcessExecution) -> RunResult:
        if not request.argv:
            raise ValueError("process argv must not be empty")
        await self._ensure_connected()
        return await self._exec_argv(request.argv, request.stdin, {
            **self.config.env,
            **request.env
        }, request.cwd.virtual)

    async def _exec_argv(self, argv: tuple[str, ...], stdin: bytes | None,
                         env: dict[str, str], cwd: str) -> RunResult:
        args = ["exec", "-i", "-w", "/"]
        for key, value in env.items():
            args += ["-e", f"{key}={value}"]
        args += [self.config.container, "sh", "-c", PRELUDE, "sh", cwd, *argv]
        stdout, stderr, code = await self._container(args, stdin=stdin)
        return RunResult(stdout=stdout, stderr=stderr, exit_code=code)
