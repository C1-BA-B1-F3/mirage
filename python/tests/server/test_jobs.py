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
import functools

import pytest

from mirage.server.jobs import JobStatus, JobTable


def submit(table, work):
    return table.submit(
        "ws",
        "probe",
        functools.partial(
            asyncio.run_coroutine_threadsafe, loop=asyncio.get_running_loop()
        ),
        work,
    )


@pytest.mark.asyncio
async def test_cancel_waits_for_coroutine_cleanup():
    entered, cleanup, release = (asyncio.Event() for _ in range(3))

    async def work():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleanup.set()
            await release.wait()

    table = JobTable()
    job = submit(table, work)
    await entered.wait()
    assert table.cancel(job.id)
    await cleanup.wait()
    waiting = asyncio.create_task(table.wait(job.id))
    await asyncio.sleep(0)
    assert not waiting.done()
    assert job.finished_at is None
    assert not table.cancel(job.id)
    release.set()
    assert (await waiting).status == JobStatus.CANCELED


@pytest.mark.asyncio
async def test_cancel_before_start_does_not_invoke_factory():
    table = JobTable()
    invoked = False

    async def work():
        nonlocal invoked
        invoked = True

    job = submit(table, work)
    assert table.cancel(job.id)
    assert (await table.wait(job.id)).status == JobStatus.CANCELED
    assert not invoked


@pytest.mark.asyncio
async def test_retention_bounds_completed_jobs_but_keeps_active(monkeypatch):
    table = JobTable(max_completed=2, retention_seconds=10)
    release = asyncio.Event()
    active = submit(table, release.wait)
    finished = []
    for _ in range(3):
        job = submit(table, lambda: asyncio.sleep(0, result="value"))
        await table.wait(job.id)
        finished.append(job)
    assert finished[0].id not in table
    assert len(table.list()) == 3
    monkeypatch.setattr(
        "mirage.server.jobs.time.time", lambda: finished[-1].finished_at + 11
    )
    assert table.list() == [active]
    release.set()
    await table.wait(active.id)
