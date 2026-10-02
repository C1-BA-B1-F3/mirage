import pytest

from mirage.commands.builtin.generic.tsort import tsort
from mirage.types import PathSpec
from mirage.utils.key_prefix import mount_key


def _spec(path: str) -> PathSpec:
    return PathSpec(
        vfs_path=mount_key(path, ""),
        virtual=path,
        directory=path,
        resolved=True,
    )


def _read_bytes(files: dict[str, bytes]):

    async def read_bytes(path: PathSpec) -> bytes:
        if path.virtual not in files:
            raise FileNotFoundError(path.virtual)
        return files[path.virtual]

    return read_bytes


@pytest.mark.asyncio
async def test_tsort_basic():
    rb = _read_bytes({"deps": b"a b\nb c\n"})
    out, io = await tsort([_spec("deps")], read_bytes=rb)
    assert out == b"a\nb\nc\n"
    assert io.exit_code == 0


@pytest.mark.asyncio
async def test_tsort_cycle_detection():
    rb = _read_bytes({"deps": b"a b\nb a\n"})
    out, io = await tsort([_spec("deps")], read_bytes=rb)
    assert b"cycle" in out
    assert io.exit_code == 1


@pytest.mark.asyncio
async def test_tsort_stdin():
    out, io = await tsort([], read_bytes=_read_bytes({}), stdin=b"x y\ny z\n")
    assert out == b"x\ny\nz\n"
