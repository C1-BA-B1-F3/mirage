import asyncio

from mirage.ops.ram import OPS as RAM_OPS
from mirage.ops.registry import RegisteredOp
from mirage.types import FileStat, FileType, PathSpec
from mirage.vfs.ram import RAMVFS


class VersionedVFS(RAMVFS):
    """A RAM mount whose listing version and folder stat a test controls.

    ``index_ttl`` is positive so a ``fresh`` mount keeps listings for the
    gate to check. ``stats`` is the ledger of every stat the backend was
    sent, ``sent`` is set as each one arrives, and a stat waits on ``hold``
    when one is given, so a test orders concurrent checks with events.
    """

    index_ttl: float = 600

    def __init__(
        self,
        kind: str = "none",
        remote: str | None = "v1",
        has_stat: bool = True,
    ) -> None:
        """Args:
        kind (str): the listing version the mount declares, by value;
            "none" keeps the class default.
        remote (str | None): the fingerprint every stat answers unless
            ``remotes`` names the path.
        has_stat (bool): whether the mount registers a stat op at all.
        """
        super().__init__()
        if kind != "none":
            self.listing_version = kind
        self.remote = remote
        self.remotes: dict[str, str | None] = {}
        self.raises: Exception | None = None
        self.hold: asyncio.Event | None = None
        self.sent = asyncio.Event()
        self.stats: list[str] = []
        self._has_stat = has_stat

    def ops(self) -> list[RegisteredOp]:
        rest = [o for o in RAM_OPS if o.name != "stat"]
        if not self._has_stat:
            return rest
        return rest + [
            RegisteredOp(name="stat", vfs="ram", filetype=None, fn=self._stat)
        ]

    async def _stat(self, accessor, path: PathSpec, **kwargs) -> FileStat:
        self.stats.append(path.virtual)
        self.sent.set()
        if self.hold is not None:
            await self.hold.wait()
        if self.raises is not None:
            raise self.raises
        return FileStat(
            name=path.virtual.rsplit("/", 1)[-1] or "/",
            type=FileType.DIRECTORY,
            fingerprint=self.remotes.get(path.virtual, self.remote),
        )
