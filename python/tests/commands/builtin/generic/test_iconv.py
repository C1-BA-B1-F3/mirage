import pytest

from mirage.commands.builtin.generic.iconv import iconv
from mirage.types import PathSpec


async def _unused_read_bytes(path):
    raise AssertionError(f"iconv read {path} although stdin was given")


def _store():
    store: dict[str, bytes] = {}

    async def write_bytes(path: PathSpec, data: bytes) -> None:
        store[path.virtual] = data

    return store, write_bytes


@pytest.mark.asyncio
async def test_iconv_encoding_conversion():
    _, write_bytes = _store()
    output, _ = await iconv(
        [],
        read_bytes=_unused_read_bytes,
        write_bytes=write_bytes,
        stdin="café".encode(),
        from_enc="utf-8",
        to_enc="ascii",
        ignore_errors=True,
    )
    assert output == b"caf"


@pytest.mark.asyncio
async def test_iconv_writes_to_output_path():
    store, write_bytes = _store()
    output, io = await iconv(
        [],
        read_bytes=_unused_read_bytes,
        write_bytes=write_bytes,
        stdin=b"hello",
        from_enc="utf-8",
        to_enc="utf-8",
        output_path=PathSpec(
            vfs_path="out.txt",
            virtual="/out.txt",
            directory="/out.txt",
            resolved=True,
        ),
    )
    assert output is None
    assert store["/out.txt"] == b"hello"
    assert io.writes == {"/out.txt": b"hello"}
