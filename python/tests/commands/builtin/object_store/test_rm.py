from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from mirage.commands.builtin.generic_bind.adapter import (
    CommandIO,
    with_path_guards,
)
from mirage.commands.builtin.object_store.rm import make_rm
from mirage.commands.config import CommandOpts
from mirage.types import FileStat, FileType, PathSpec


@pytest.mark.asyncio
@pytest.mark.parametrize("force", [False, True])
@pytest.mark.parametrize(
    "refusal,raw,message",
    [
        ("ENOENT", "", "No such file or directory"),
        ("ELOOP", "loop/child", "Too many levels of symbolic links"),
    ],
)
async def test_rm_refused_operand_keeps_spelling_and_continues(
    force, refusal, raw, message
):
    stat = AsyncMock(return_value=FileStat(name="ok", type=FileType.FILE))
    unlink = AsyncMock()
    io = with_path_guards(
        CommandIO(
            readdir=AsyncMock(return_value=[]),
            read_bytes=AsyncMock(),
            read_stream=AsyncMock(),
            stat=stat,
            is_mounted=lambda _: True,
            unlink=unlink,
            rmdir=AsyncMock(),
            rm_r=AsyncMock(),
        )
    )
    refused = replace(
        PathSpec.from_str_path("/data"), raw_path=raw, walk_error=refusal
    )
    valid = PathSpec.from_str_path("/data/ok")
    _, result = await make_rm("s3", io)(
        None, [refused, valid], [], CommandOpts(flags={"f": force})
    )
    ignored = force and refusal == "ENOENT"
    assert result.exit_code == (0 if ignored else 1)
    assert result.stderr == (
        None if ignored else f"rm: cannot remove '{raw}': {message}\n".encode()
    )
    assert stat.await_count == 1
    assert unlink.await_args.args[1] == valid
