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

from mirage.runtime.sandbox.base import RemoteSandbox
from mirage.runtime.sandbox.cli import run_cli
from mirage.runtime.sandbox.docker.config import DockerConfig
from mirage.runtime.sandbox.docker.constants import DOCKER_CLI_HINT
from mirage.runtime.types import RunResult


class DockerRuntime(RemoteSandbox):
    """A container the user runs as a whole-line runtime.

    You start the container yourself; mirage only connects to it and
    execs lines. The docker CLI is the transport (Docker Desktop,
    colima, or a podman alias all work), so there is no SDK dependency
    and no daemon socket wiring; each line is one `docker exec -i`
    with the merged environment, the rebased cwd, real stdin, and
    separated stderr.

    Args:
        options (Any): the RemoteSandbox constructor fields.
    """

    name = "docker"
    config_cls = DockerConfig
    config: DockerConfig

    async def _docker(
        self, args: list[str], stdin: bytes | None = None
    ) -> tuple[bytes, bytes, int]:
        """One docker CLI invocation; the seam tests override."""
        return await run_cli("docker", DOCKER_CLI_HINT, args, stdin)

    async def connect(self) -> None:
        stdout, stderr, code = await self._docker(
            [
                "inspect",
                "--format",
                "{{.State.Running}}",
                self.config.container,
            ]
        )
        if code != 0:
            raise RuntimeError(
                f"docker inspect failed: {stderr.decode().strip()}"
            )
        if stdout.decode().strip() != "true":
            raise RuntimeError(
                f"container {self.config.container} is not running"
            )

    async def exec_line(
        self, line: str, stdin: bytes | None, env: dict[str, str], cwd: str
    ) -> RunResult:
        args = ["exec", "-i", "-w", cwd]
        for key, value in env.items():
            args += ["-e", f"{key}={value}"]
        args += [self.config.container, "sh", "-c", line]
        stdout, stderr, code = await self._docker(args, stdin=stdin)
        return RunResult(stdout=stdout, stderr=stderr, exit_code=code)
