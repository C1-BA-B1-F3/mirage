import pytest

from mirage.commands.builtin.generic.rev import rev


async def _unused_read_bytes(path):
    raise AssertionError(f"rev read {path} although it had no operand")


@pytest.mark.asyncio
async def test_rev_missing_input_raises():
    with pytest.raises(ValueError, match="missing operand"):
        await rev([], read_bytes=_unused_read_bytes)
