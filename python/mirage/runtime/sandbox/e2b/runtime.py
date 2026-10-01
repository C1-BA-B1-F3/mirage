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

import logging
from typing import Any

from mirage.runtime.sandbox.base import RemoteSandbox
from mirage.runtime.sandbox.constants import sdk_install_hint
from mirage.runtime.sandbox.e2b import sdk
from mirage.runtime.sandbox.e2b.config import E2BConfig
from mirage.runtime.types import RunResult

logger = logging.getLogger(__name__)


class E2BRuntime(RemoteSandbox):
    """An E2B sandbox the user runs as a whole-line runtime.

    You create the sandbox yourself (`e2b sandbox spawn` or the SDK);
    mirage only connects by ``sandbox_id`` and execs lines.
    ``api_key`` falls back to E2B_API_KEY. E2B's exec reports stdout
    and stderr separately. Piped bytes use native stdin followed by
    an explicit EOF; no input closes stdin when the command starts.

    Args:
        options (Any): the RemoteSandbox constructor fields.
    """

    name = "e2b"
    config_cls = E2BConfig
    config: E2BConfig
    _sandbox: Any = None

    def _api_params(self) -> dict[str, Any]:
        api_key = self.config.api_key
        return {"api_key": api_key} if api_key is not None else {}

    async def connect(self) -> None:
        if sdk.AsyncSandbox is None:
            raise ImportError(sdk_install_hint("e2b"))
        self._sandbox = await sdk.AsyncSandbox.connect(
            self.config.sandbox_id, **self._api_params()
        )

    async def exec_line(
        self, line: str, stdin: bytes | None, env: dict[str, str], cwd: str
    ) -> RunResult:
        handle = await self._sandbox.commands.run(
            line, envs=env, cwd=cwd, background=True, stdin=stdin is not None
        )
        try:
            try:
                if stdin is not None:
                    if stdin:
                        await handle.send_stdin(stdin)
                    await handle.close_stdin()
            except sdk.NotFoundException:
                # A command may exit before the input RPC arrives. Its exit
                # status, including nonzero exits, still determines the result.
                result = await handle.wait()
            else:
                result = await handle.wait()
        except sdk.CommandExitException as exc:
            result = exc
        except BaseException:
            try:
                await handle.kill()
            except Exception:
                logger.warning("Failed to stop the E2B command", exc_info=True)
            raise
        finally:
            await handle.disconnect()
        return RunResult(
            stdout=str(result.stdout).encode(),
            stderr=str(result.stderr).encode(),
            exit_code=int(result.exit_code),
        )
