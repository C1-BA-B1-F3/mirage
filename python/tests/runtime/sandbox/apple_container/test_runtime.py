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

import json
import subprocess

import pytest

from mirage.runtime.sandbox.apple_container import AppleContainerRuntime
from mirage.runtime.sandbox.apple_container.constants import PRELUDE
from mirage.runtime.table import build_runtime
from mirage.runtime.types import ProcessExecution, ShellExecution
from mirage.types import PathSpec


class FakeAppleContainerRuntime(AppleContainerRuntime):

    def __init__(self,
                 state: str = "running",
                 inspect_code: int = 0,
                 inspect_stdout: bytes | None = None,
                 **options):
        super().__init__(**options)
        self.state = state
        self.inspect_code = inspect_code
        self.inspect_stdout = inspect_stdout
        self.calls: list[tuple[list[str], bytes | None]] = []

    async def _container(self, args, stdin=None):
        self.calls.append((list(args), stdin))
        if args[0] == "inspect":
            if self.inspect_stdout is not None:
                return self.inspect_stdout, b"", self.inspect_code
            if self.inspect_code != 0:
                return (b"", b"Error: container not found: box",
                        self.inspect_code)
            return json.dumps([{
                "id": "box",
                "configuration": {},
                "status": {
                    "state": self.state
                }
            }]).encode(), b"", 0
        script = args[-1]
        return f"out:{script}".encode(), b"warn", 0


def prelude(cwd: str, *argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(["/bin/sh", "-c", PRELUDE, "sh", cwd, *argv],
                          capture_output=True,
                          check=False)


@pytest.mark.asyncio
async def test_connect_inspects_the_users_container():
    runtime = FakeAppleContainerRuntime(config={"container": "box"})
    await runtime.connect()
    args, _ = runtime.calls[0]
    assert args == ["inspect", "box"]


@pytest.mark.asyncio
@pytest.mark.parametrize(("state", "hint"), [
    ("stopped", "start it with `container start box`"),
    ("stopping", "shutting down"),
    ("unknown", r"state: unknown"),
])
async def test_connect_names_why_a_state_cannot_take_a_line(state, hint):
    runtime = FakeAppleContainerRuntime(state=state,
                                        config={"container": "box"})
    with pytest.raises(RuntimeError, match=hint):
        await runtime.connect()


@pytest.mark.asyncio
async def test_connect_fails_loud_when_the_cli_errors():
    runtime = FakeAppleContainerRuntime(inspect_code=1,
                                        config={"container": "box"})
    with pytest.raises(RuntimeError, match="container not found: box"):
        await runtime.connect()


@pytest.mark.asyncio
@pytest.mark.parametrize("stdout",
                         [b"not json", b"[]", b"{}", b'[{"status": null}]'])
async def test_connect_fails_loud_on_unreadable_json(stdout):
    runtime = FakeAppleContainerRuntime(inspect_stdout=stdout,
                                        config={"container": "box"})
    with pytest.raises(RuntimeError, match="unreadable json"):
        await runtime.connect()


def test_container_is_required():
    with pytest.raises(TypeError, match="container"):
        AppleContainerRuntime(config={})


def test_registers_under_the_config_name():
    runtime = build_runtime("apple_container", config={"container": "box"})
    assert isinstance(runtime, AppleContainerRuntime)
    assert runtime.captures == ("@external", )
    assert runtime.reach == "remote"


@pytest.mark.asyncio
async def test_exec_line_runs_under_the_prelude_with_stdin_and_stderr():
    runtime = FakeAppleContainerRuntime(config={"container": "box"})
    result = await runtime.exec_line("wc -l", b"a\nb\n", {"E": "1"},
                                     "/root/workspace")
    assert result.exit_code == 0
    assert result.stdout == b"out:wc -l"
    assert result.stderr == b"warn"
    args, stdin = runtime.calls[-1]
    assert args == [
        "exec", "-i", "-w", "/", "-e", "E=1", "box", "sh", "-c", PRELUDE, "sh",
        "/root/workspace", "sh", "-c", "wc -l"
    ]
    assert stdin == b"a\nb\n"


@pytest.mark.asyncio
async def test_process_preserves_argv_and_shares_the_shell_connection():
    runtime = FakeAppleContainerRuntime(config={
        "container": "box",
        "env": {
            "E": "config"
        }
    })
    argv = ("node", "a b", "$(echo literal)", "", "--flag")
    result = await runtime.execute(
        ProcessExecution(argv=argv,
                         cwd=PathSpec.from_str_path("/work"),
                         env={"E": "request"},
                         stdin=b"input"))
    assert result.stdout == b"out:--flag"
    assert result.stderr == b"warn"
    assert runtime.calls[-1] == ([
        "exec", "-i", "-w", "/", "-e", "E=request", "box", "sh", "-c", PRELUDE,
        "sh", "/work", *argv
    ], b"input")
    await runtime.execute(
        ShellExecution(line="pwd", cwd=PathSpec.from_str_path("/work")))
    assert sum(args[0] == "inspect" for args, _ in runtime.calls) == 1
    assert runtime.capabilities.process and runtime.capabilities.shell
    assert runtime.capabilities.filesystem == ()


@pytest.mark.asyncio
async def test_process_refuses_a_stopped_container_and_empty_argv():
    runtime = FakeAppleContainerRuntime(state="stopped",
                                        config={"container": "box"})
    with pytest.raises(ValueError, match="argv must not be empty"):
        await runtime.execute(
            ProcessExecution(argv=(), cwd=PathSpec.from_str_path("/")))
    assert not runtime.calls
    with pytest.raises(RuntimeError, match="not running"):
        await runtime.execute(
            ProcessExecution(argv=("node", ), cwd=PathSpec.from_str_path("/")))
    assert len(runtime.calls) == 1


@pytest.mark.asyncio
async def test_a_missing_cli_names_how_to_install_it(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    runtime = AppleContainerRuntime(config={"container": "box"})
    with pytest.raises(RuntimeError, match="brew install container"):
        await runtime.connect()


def test_prelude_enters_the_cwd_and_hands_over_argv_unchanged(tmp_path):
    done = prelude(str(tmp_path), "sh", "-c", 'pwd; printf "[%s]\\n" "$@"',
                   "sh", "a b", "$(echo literal)", "", "--flag")
    assert done.returncode == 0
    assert done.stdout.decode().splitlines() == [
        str(tmp_path), "[a b]", "[$(echo literal)]", "[]", "[--flag]"
    ]


def test_prelude_fails_loud_on_a_missing_cwd_and_creates_nothing(tmp_path):
    missing = tmp_path / "unserved"
    done = prelude(str(missing), "pwd")
    assert done.returncode != 0
    assert done.stdout == b""
    assert str(missing) in done.stderr.decode()
    assert not missing.exists()


def test_prelude_keeps_the_exit_code():
    assert prelude("/", "sh", "-c", "exit 7").returncode == 7
