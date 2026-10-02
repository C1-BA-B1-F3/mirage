import pytest

from mirage.commands.builtin.generic.strings import strings


async def _unused_read_bytes(path):
    raise AssertionError(f"strings read {path} although stdin was given")


@pytest.mark.asyncio
async def test_strings_min_len_filter():
    binary = b"hi\x00longer_string\x00"
    output, _ = await strings(
        [], read_bytes=_unused_read_bytes, stdin=binary, min_len=5
    )
    decoded = output.decode()
    assert "longer_string" in decoded
    assert "hi" not in decoded
