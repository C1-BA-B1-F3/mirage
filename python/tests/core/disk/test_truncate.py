import pytest

from mirage.accessor.disk import DiskAccessor
from mirage.core.disk.truncate import truncate
from mirage.types import PathSpec


@pytest.mark.asyncio
@pytest.mark.parametrize("no_create", [False, True])
async def test_truncate_creation_is_an_open_precondition(tmp_path, no_create):
    accessor = DiskAccessor(str(tmp_path))
    path = PathSpec.from_str_path("/file")
    await truncate(accessor, path, 3, no_create)
    if no_create:
        assert not (tmp_path / "file").exists()
    else:
        assert (tmp_path / "file").read_bytes() == b"\0" * 3


@pytest.mark.asyncio
async def test_truncate_preserves_the_prefix_and_zero_fills(tmp_path):
    accessor = DiskAccessor(str(tmp_path))
    (tmp_path / "file").write_bytes(b"hello")
    path = PathSpec.from_str_path("/file")
    await truncate(accessor, path, 2, True)
    assert (tmp_path / "file").read_bytes() == b"he"
    await truncate(accessor, path, 4, True)
    assert (tmp_path / "file").read_bytes() == b"he\0\0"
