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
import os

import pytest

from mirage.runtime.sandbox.cli import run_cli


@pytest.mark.asyncio
async def test_run_cli_returns_both_streams_and_the_status():
    out, err, code = await run_cli(
        "sh", "no sh", ["-c", "cat; echo e >&2; exit 3"], b"in"
    )
    assert (out, err, code) == (b"in", b"e\n", 3)


@pytest.mark.asyncio
async def test_a_missing_cli_raises_its_hint():
    with pytest.raises(RuntimeError, match="install it"):
        await run_cli("mirage-no-such-cli", "install it", [], None)


@pytest.mark.asyncio
async def test_cancelling_a_call_kills_the_child(tmp_path):
    pid_file = tmp_path / "pid"
    task = asyncio.create_task(
        run_cli(
            "sh", "no sh", ["-c", f"echo $$ > {pid_file}; exec sleep 30"], None
        )
    )
    for _ in range(200):
        if pid_file.exists() and pid_file.read_text().strip():
            break
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    pid = int(pid_file.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
