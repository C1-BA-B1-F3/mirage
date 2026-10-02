from abc import ABC, abstractmethod

from mirage.execution.types import ExecutionRecord


class ExecutionStore(ABC):
    """Async request tracking; live tasks and process handles stay with the owner.

    Records are independent snapshots. Revisions increase on successful CAS.
    A wait observes a revision, so a change before subscription is not lost.
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
    ) -> list[ExecutionRecord]: ...

    @abstractmethod
    async def compare_and_set(
        self, record: ExecutionRecord, revision: int
    ) -> bool:
        """Replace iff revision matches; the replacement has revision + 1."""

    @abstractmethod
    async def wait_for_change(
        self, execution_id: str, revision: int, timeout: float | None = None
    ) -> ExecutionRecord | None:
        """Return changed/current state, or None if it has expired."""

    @abstractmethod
    async def close(self) -> None: ...
