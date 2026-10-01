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
import concurrent.futures
import logging
import secrets
import threading
import time
from collections import deque
from enum import Enum
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELED = "canceled"


def new_job_id() -> str:
    """Mint a fresh job id of the form ``job_<16 hex chars>``."""
    return f"job_{secrets.token_hex(8)}"


class JobEntry:
    """One in-flight or completed daemon-level execute job."""

    def __init__(self, job_id: str, workspace_id: str, command: str) -> None:
        self.id = job_id
        self.workspace_id = workspace_id
        self.command = command
        self.status: JobStatus = JobStatus.PENDING
        self.result: Any = None
        self.error: str | None = None
        self.submitted_at: float = time.time()
        self.started_at: float | None = None
        self.finished_at: float | None = None
        self._task: asyncio.Task[Any] | None = None
        self._cancel = threading.Event()
        self._done_event: asyncio.Event = asyncio.Event()


class JobTable:
    """Daemon-wide table of execute jobs.

    Tracks both sync and background jobs so the CLI can query
    progress, wait, and cancel uniformly. Sync calls register the job
    in pending/running and complete it before returning. Completed records
    expire after one hour and are bounded to the latest 1024;
    running jobs are never evicted. Pruning runs on completion and access.
    """

    def __init__(
        self, max_completed: int = 1024, retention_seconds: float = 3600
    ) -> None:
        if max_completed < 1 or retention_seconds <= 0:
            raise ValueError("job retention limits must be positive")
        self._jobs: dict[str, JobEntry] = {}
        self._completed: deque[str] = deque()
        self._max_completed = max_completed
        self._retention_seconds = retention_seconds

    def _prune(self) -> None:
        cutoff = time.time() - self._retention_seconds
        while self._completed:
            job = self._jobs[self._completed[0]]
            if (
                len(self._completed) <= self._max_completed
                and job.finished_at is not None
                and job.finished_at > cutoff
            ):
                break
            del self._jobs[self._completed.popleft()]

    def __contains__(self, job_id: str) -> bool:
        self._prune()
        return job_id in self._jobs

    def get(self, job_id: str) -> JobEntry:
        self._prune()
        return self._jobs[job_id]

    def list(self, workspace_id: str | None = None) -> list[JobEntry]:
        self._prune()
        if workspace_id is None:
            return list(self._jobs.values())
        return [
            j for j in self._jobs.values() if j.workspace_id == workspace_id
        ]

    def submit(
        self,
        workspace_id: str,
        command: str,
        schedule: Callable[[Awaitable[Any]], concurrent.futures.Future[Any]],
        coro_factory: Callable[[], Awaitable[Any]],
    ) -> JobEntry:
        """Register work; completion is published only after its coroutine unwinds.

        Args:
            workspace_id (str): owning workspace.
            command (str): display command.
            schedule (Callable): schedules a coroutine on the workspace loop.
            coro_factory (Callable): creates the work on that loop.
        """
        self._prune()
        entry = JobEntry(new_job_id(), workspace_id, command)
        self._jobs[entry.id] = entry
        entry.status = JobStatus.RUNNING
        entry.started_at = time.time()
        run = self._run(entry, coro_factory, asyncio.get_running_loop())
        try:
            schedule(run)
        except Exception as exc:
            run.close()
            self._finish(
                entry, JobStatus.FAILED, None, f"{type(exc).__name__}: {exc}"
            )
        return entry

    async def _run(
        self,
        entry: JobEntry,
        factory: Callable[[], Awaitable[Any]],
        owner: asyncio.AbstractEventLoop,
    ) -> None:
        entry._task = asyncio.current_task()
        status, result, error = JobStatus.DONE, None, None
        try:
            if entry._cancel.is_set():
                raise asyncio.CancelledError()
            result = await factory()
        except asyncio.CancelledError:
            status = JobStatus.CANCELED
        except Exception as exc:
            status, error = JobStatus.FAILED, f"{type(exc).__name__}: {exc}"
        finally:
            owner.call_soon_threadsafe(
                self._finish, entry, status, result, error
            )

    def _finish(
        self,
        entry: JobEntry,
        status: JobStatus,
        result: Any,
        error: str | None,
    ) -> None:
        entry.status = JobStatus.CANCELED if entry._cancel.is_set() else status
        entry.result = result if entry.status == JobStatus.DONE else None
        entry.error = error
        entry._task = None
        entry.finished_at = time.time()
        entry._done_event.set()
        self._completed.append(entry.id)
        self._prune()

    async def wait(
        self, job_id: str, timeout: float | None = None
    ) -> JobEntry:
        entry = self.get(job_id)
        if entry.finished_at is not None:
            return entry
        try:
            await asyncio.wait_for(entry._done_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return entry
        return entry

    def cancel(self, job_id: str) -> bool:
        entry = self.get(job_id)
        if entry.finished_at is not None:
            return False
        if entry._cancel.is_set():
            return False
        entry._cancel.set()
        task = entry._task
        if task is not None:
            task.get_loop().call_soon_threadsafe(task.cancel)
        return True
