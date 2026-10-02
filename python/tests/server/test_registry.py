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

import pytest

from mirage import RAMVFS, MountMode, Workspace
from mirage.server.registry import WorkspaceRegistry


@pytest.mark.asyncio
async def test_an_overlapping_remove_joins_the_deletion_in_flight(
    monkeypatch,
):
    # A second deletion of its own would stop the runner again and run
    # its cleanup, then release the id after a create had reused it.
    registry = WorkspaceRegistry(idle_grace_seconds=10.0)
    entry = registry.add(Workspace({"/": (RAMVFS(), MountMode.WRITE)}), "w")
    stops: list[bool] = []
    cleanups: list[str] = []
    stop = entry.runner.stop

    async def counted_stop(*, delete: bool = False) -> None:
        stops.append(delete)
        await stop(delete=delete)

    async def cleanup() -> None:
        cleanups.append("w")

    monkeypatch.setattr(entry.runner, "stop", counted_stop)
    first, second = await asyncio.gather(
        registry.remove("w", cleanup), registry.remove("w", cleanup)
    )
    assert first is second is entry
    assert stops == [True]
    assert cleanups == ["w"]
    assert "w" not in registry
