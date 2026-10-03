import pytest

from mirage.commands.builtin.generic.rev import rev


async def _unused_read_bytes(path):
    raise AssertionError(f"rev read {path} although it had no operand")


@pytest.mark.asyncio
async def test_rev_without_stdin_reads_empty_input():
    out, io = await rev([], read_bytes=_unused_read_bytes)
    assert (out, io.exit_code) == (b"", 0)
