import pytest

from mirage.commands.builtin.generic.md5 import md5


async def _unused_read_bytes(path):
    raise AssertionError(f"md5 read {path} although it had no operand")


@pytest.mark.asyncio
async def test_md5_no_paths_raises():
    with pytest.raises(ValueError, match="missing operand"):
        await md5([], read_bytes=_unused_read_bytes)
