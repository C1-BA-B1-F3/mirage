import asyncio
import time
from collections import deque
from copy import deepcopy

from mirage.execution.base import ExecutionStore
from mirage.execution.types import ExecutionRecord


class RAMExecutionStore(ExecutionStore):
    """Records owned by one event loop, with bounded completed retention."""

    def __init__(
        self, max_completed: int = 1024, retention_seconds: float = 3600
    ) -> None:
        if max_completed < 1 or retention_seconds <= 0:
            raise ValueError("execution retention limits must be positive")
        self._records: dict[str, ExecutionRecord] = {}
        self._completed: deque[str] = deque()
        self._changed = asyncio.Condition()
        self._closed = False
        self._max_completed = max_completed
        self._retention_seconds = retention_seconds

    def _prune(self) -> None:
        if self._closed:
            raise RuntimeError("execution store is closed")
        cutoff = time.time() - self._retention_seconds
        while self._completed:
            record = self._records[self._completed[0]]
            if (
                len(self._completed) <= self._max_completed
                and record.finished_at is not None
                and record.finished_at > cutoff
            ):
                break
            del self._records[self._completed.popleft()]

    async def create(self, record: ExecutionRecord) -> bool:
        async with self._changed:
            self._prune()
            if record.id in self._records:
                return False
            self._records[record.id] = deepcopy(record)
            self._changed.notify_all()
            return True

    async def get(self, execution_id: str) -> ExecutionRecord | None:
        self._prune()
        return deepcopy(self._records.get(execution_id))

    async def list(
        self, workspace_id: str | None = None
    ) -> list[ExecutionRecord]:
        self._prune()
        return deepcopy(
            [
                r
                for r in self._records.values()
                if workspace_id is None or r.workspace_id == workspace_id
            ]
        )

    async def compare_and_set(
        self, record: ExecutionRecord, revision: int
    ) -> bool:
        async with self._changed:
            self._prune()
            previous = self._records.get(record.id)
            if previous is None or previous.revision != revision:
                return False
            if previous.finished_at is not None:
                return False
            if record.revision != revision + 1:
                raise ValueError("replacement must increment the revision")
            if previous.cancel_requested and not record.cancel_requested:
                raise ValueError("cancellation intent cannot be cleared")
            if (record.workspace_id, record.session_id, record.command) != (
                previous.workspace_id,
                previous.session_id,
                previous.command,
            ):
                raise ValueError("execution identity cannot change")
            self._records[record.id] = deepcopy(record)
            if record.finished_at is not None:
                self._completed.append(record.id)
            self._prune()
            self._changed.notify_all()
            return True

    async def wait_for_change(
        self, execution_id: str, revision: int, timeout: float | None = None
    ) -> ExecutionRecord | None:
        async with self._changed:
            try:
                async with asyncio.timeout(timeout):
                    while True:
                        record = await self.get(execution_id)
                        if record is None or record.revision != revision:
                            return record
                        await self._changed.wait()
            except TimeoutError:
                return await self.get(execution_id)

    async def close(self) -> None:
        async with self._changed:
            self._closed = True
            self._changed.notify_all()
