import pytest

from mirage.commands.builtin.generic.tr import tr
from mirage.io.stream import materialize


def _unused_read_stream(_path):
    raise AssertionError("read_stream should not be called for stdin input")


async def _run(texts, flags, data):
    source, io = await tr(
        [],
        tuple(texts),
        read_stream=_unused_read_stream,
        stdin=data,
        flags=flags,
    )
    return io.exit_code, (await materialize(source)).decode()


@pytest.mark.asyncio
async def test_default_pads_set2_to_set1_length():
    _, out = await _run(["abcde", "xy"], {}, b"abcde")
    assert out == "xyyyy"


@pytest.mark.asyncio
async def test_long_forms():
    _, comp = await _run(["0-9", "_"], {"complement": True}, b"abc123")
    assert comp == "___123"
    _, trunc = await _run(["abcde", "xy"], {"truncate_set1": True}, b"abcde")
    assert trunc == "xycde"
    _, deleted = await _run(["abc"], {"delete": True}, b"aabbccdd")
    assert deleted == "dd"
    _, squeezed = await _run(["a-c"], {"squeeze_repeats": True}, b"aabbcc")
    assert squeezed == "abc"


@pytest.mark.asyncio
async def test_delete_without_squeeze_names_the_second_operand_as_extra():
    with pytest.raises(
        ValueError, match="extra operand 'b'\nOnly one string may be given"
    ):
        await _run(["a", "b"], {"delete": True}, b"x")
    with pytest.raises(Exception, match=r"extra operand 'b'\nTry"):
        await _run(["a", "b", "c"], {"delete": True}, b"x")
    with pytest.raises(Exception, match=r"extra operand 'c'\nTry"):
        await _run(
            ["a", "b", "c"], {"delete": True, "squeeze_repeats": True}, b"x"
        )
    with pytest.raises(Exception, match=r"extra operand 'c'\nTry"):
        await _run(["a", "b", "c"], {}, b"x")
