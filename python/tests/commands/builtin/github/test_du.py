# ========= Copyright 2026 @ Strukto.AI All Rights Reserved. =========
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ========= Copyright 2026 @ Strukto.AI All Rights Reserved. =========

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from mirage.commands.builtin.generic_bind.adapter import CommandIO
from mirage.commands.builtin.github.du import du
from mirage.commands.config import CommandOpts
from mirage.io.stream import materialize
from mirage.types import FileStat, FileType, PathSpec


async def _readdir(_accessor, path, _index):
    if path.virtual == "/db/sealed":
        raise PermissionError(13, "Permission denied", path.virtual)
    return (
        ["/db/a", "/db/empty", "/db/sealed", "/db/walled"]
        if path.virtual == "/db"
        else []
    )


async def _stat(_accessor, path, _index):
    if path.virtual == "/db/walled":
        raise PermissionError(13, "Permission denied", path.virtual)
    return FileStat(
        name=path.virtual,
        type=FileType.FILE if path.virtual == "/db/a" else FileType.DIRECTORY,
        size=3 if path.virtual == "/db/a" else None,
    )


async def _resolve(_accessor, paths, _index):
    return paths


@pytest.mark.asyncio
async def test_truncated_du_preserves_directory_rows_and_permission_errors(
    monkeypatch,
):
    ops = CommandIO(
        readdir=_readdir,
        stat=_stat,
        read_bytes=AsyncMock(),
        read_stream=AsyncMock(),
        is_mounted=lambda _: True,
    )
    monkeypatch.setitem(du.__wrapped__.__globals__, "IO", ops)
    monkeypatch.setitem(du.__wrapped__.__globals__, "ensure_tree", AsyncMock())
    monkeypatch.setitem(du.__wrapped__.__globals__, "resolve_glob", _resolve)
    stream, io = await du.__wrapped__(
        SimpleNamespace(truncated=True),
        [PathSpec.from_str_path("/db")],
        [],
        CommandOpts(),
    )
    assert (
        await materialize(stream)
    ).decode() == "0\t/db/empty\n0\t/db/sealed\n3\t/db\n"
    assert io.exit_code == 1
    assert await io.stderr_str() == (
        "du: cannot read directory '/db/sealed': Permission denied\n"
        "du: cannot read directory '/db/walled': Permission denied\n"
    )
