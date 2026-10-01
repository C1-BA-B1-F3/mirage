import asyncio

import pytest

from mirage.cache.index import NULL_INDEX
from mirage.core.generic.du import make_walked_du
from mirage.types import FileStat, FileType, PathSpec

FILES = {"/m/a.txt": 3, "/m/sub/b.txt": 4, "/m/sub/c.txt": 5}
DIRS = {
    "/m": ["/m/sub/", "/m/a.txt"],
    "/m/sub": ["/m/sub/c.txt", "/m/sub/b.txt"],
}


def _spec(virtual: str) -> PathSpec:
    return PathSpec(
        virtual=virtual,
        directory=virtual,
        vfs_path=virtual.removeprefix("/m").lstrip("/"),
    )


async def _stat(accessor, path, index=NULL_INDEX) -> FileStat:
    if path.virtual in DIRS:
        return FileStat(name=path.virtual, type=FileType.DIRECTORY)
    if path.virtual in FILES:
        return FileStat(
            name=path.virtual, type=FileType.FILE, size=FILES[path.virtual]
        )
    raise FileNotFoundError(path.virtual)


async def _readdir(accessor, path, index=NULL_INDEX) -> list[str]:
    return DIRS[path.virtual]


DU = make_walked_du(_stat, _readdir)


def test_size_and_entries_walk_the_subtree():
    assert asyncio.run(DU.size(None, _spec("/m"))) == 12
    assert asyncio.run(DU.entries(None, _spec("/m"))) == (
        [("/a.txt", 3), ("/sub/b.txt", 4), ("/sub/c.txt", 5)],
        12,
    )


def test_a_file_has_no_entries_and_its_own_size():
    assert asyncio.run(DU.entries(None, _spec("/m/a.txt"))) == ([], 3)


async def _ghost_readdir(accessor, path, index=NULL_INDEX) -> list[str]:
    return [*DIRS[path.virtual], f"{path.virtual}/ghost.txt"]


async def _throttled_readdir(accessor, path, index=NULL_INDEX) -> list[str]:
    raise RuntimeError("429")


def test_a_missing_path_and_a_child_gone_mid_walk_count_as_zero():
    assert asyncio.run(DU.size(None, _spec("/m/nope"))) == 0
    ghost = make_walked_du(_stat, _ghost_readdir)
    assert asyncio.run(ghost.size(None, _spec("/m"))) == 12


def test_a_failure_other_than_absence_propagates():
    with pytest.raises(RuntimeError):
        asyncio.run(
            make_walked_du(_stat, _throttled_readdir).size(None, _spec("/m"))
        )
