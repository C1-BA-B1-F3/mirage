import asyncio
from abc import ABC, abstractmethod

from mirage.execution.types import ExecutionRecord


class ExecutionStore(ABC):
    """Async request tracking; live work stays with the execution owner.

    Records are independent snapshots. Revisions increase on successful CAS.
    Implementations may expire completed records, never active executions.
    """

    @abstractmethod
    async def create(self, record: ExecutionRecord) -> bool:
        """Insert once; False means the id already exists."""

    @abstractmethod
    async def get(self, execution_id: str) -> ExecutionRecord | None: ...

    @abstractmethod
    async def list(
        self, workspace_id: str | None = None
    ) -> list[ExecutionRecord]:
        """Records without their results; ``get`` returns one in full."""

    @abstractmethod
    async def compare_and_set(
        self, record: ExecutionRecord, revision: int
    ) -> bool:
        """Replace iff revision matches; the replacement has revision + 1."""

    @abstractmethod
    async def wait_for_change(
        self,
        execution_id: str,
        revision: int,
        timeout: float | None = None,
        cancel: asyncio.Event | None = None,
    ) -> ExecutionRecord | None:
        """Return the changed or current record, None once it has expired.

        A wait observes a revision, so a change made before it registered is
        not lost. ``cancel`` ends it early with the current record, as a
        timeout does.
        """

    @abstractmethod
    async def close(self) -> None: ...
