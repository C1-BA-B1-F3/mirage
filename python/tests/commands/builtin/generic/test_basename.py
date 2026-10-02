import pytest

from mirage.commands.builtin.generic.basename import basename


@pytest.mark.asyncio
async def test_basename_empty():
    out, _ = await basename()
    assert out == b"\n"
