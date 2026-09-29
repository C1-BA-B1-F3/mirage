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

import asyncio
from dataclasses import replace
from functools import partial

import pytest

from mirage.cache.index import NULL_INDEX
from mirage.commands.builtin.generic_bind.adapter import CommandIO
from mirage.commands.builtin.generic_bind.search import run_search
from mirage.commands.builtin.utils.wrap import stream_from_bytes
from mirage.commands.config import CommandOpts
from mirage.core.hierarchy.scope import ScopeMatch
from mirage.core.hierarchy.search import make_search_op
from mirage.io.types import ByteSource
from mirage.types import ContentType, FileStat, FileType, PathSpec
from mirage.utils.errors import efbig, enoent
from mirage.vfs.types import SearchOps, SearchQuery
from tests.core.hierarchy.conftest import FakeAccessor, detect_scope, spec

CONTENT = b"x ada\ny\n"


async def _read_op(accessor: FakeAccessor,
                   path: PathSpec,
                   index=NULL_INDEX) -> bytes:
    return CONTENT


async def _stat_op(accessor: FakeAccessor,
                   path: PathSpec,
                   index=NULL_INDEX) -> FileStat:
    return FileStat(name="a.json",
                    type=FileType.FILE,
                    content=ContentType.JSON,
                    size=len(CONTENT))


async def _readdir_op(accessor: FakeAccessor,
                      path: PathSpec,
                      index=NULL_INDEX) -> list[str]:
    return []


async def _absent_stat(accessor: FakeAccessor,
                       path: PathSpec,
                       index=NULL_INDEX) -> FileStat:
    raise enoent(path.virtual)


IO = CommandIO(readdir=_readdir_op,
               read_bytes=_read_op,
               read_stream=partial(stream_from_bytes, _read_op),
               stat=_stat_op,
               is_mounted=lambda a: True,
               local=False)


async def _room_searcher(accessor: FakeAccessor, match: ScopeMatch,
                         query: SearchQuery) -> list[str]:
    return [f"rooms/{match.slots['room']}:{query.query}"]


async def _empty_searcher(accessor: FakeAccessor, match: ScopeMatch,
                          query: SearchQuery) -> list[str]:
    return []


async def _drain(source: ByteSource | None) -> bytes:
    if source is None:
        return b""
    if isinstance(source, bytes):
        return source
    chunks = [chunk async for chunk in source]
    return b"".join(chunks)


def _search_command(searchers, io, *, guard=False, stream=False):
    search = make_search_op(detect_scope, searchers,
                            io.stat if guard else None)
    return partial(
        run_search,
        replace(io,
                search=SearchOps(
                    search=search,
                    meta={"grep": {
                        "mode": "literal",
                        "stream": stream
                    }})), "grep")


def test_matched_kind_answers_from_the_searcher():
    search = _search_command({'room': _room_searcher}, IO)
    out, result = asyncio.run(
        search(FakeAccessor(), [spec("/rooms/red")], ["ada"], CommandOpts()))
    assert result.exit_code == 0
    assert asyncio.run(_drain(out)) == b"rooms/red:ada\n"


def test_empty_answer_is_exit_1():
    search = _search_command({'room': _empty_searcher}, IO)
    out, result = asyncio.run(
        search(FakeAccessor(), [spec("/rooms/red")], ["ada"], CommandOpts()))
    assert result.exit_code == 1
    assert asyncio.run(_drain(out)) == b""


def test_unmatched_kind_takes_the_generic_scan():
    search = _search_command({'room': _room_searcher}, IO)
    out, result = asyncio.run(
        search(FakeAccessor(), [spec("/rooms/red/a.json")], ["ada"],
               CommandOpts()))
    assert result.exit_code == 0
    assert b"x ada" in asyncio.run(_drain(out))


def test_shaping_flag_defers_to_the_generic_scan():
    search = _search_command({'room': _room_searcher}, IO)
    out, result = asyncio.run(
        search(FakeAccessor(), [spec("/rooms/red/a.json")], ["ada"],
               CommandOpts(flags={"v": True})))
    assert result.exit_code == 0
    drained = asyncio.run(_drain(out))
    assert b"y" in drained
    assert b"x ada" not in drained


def test_guard_probes_existence_before_searching():
    io = CommandIO(readdir=_readdir_op,
                   read_bytes=_read_op,
                   read_stream=partial(stream_from_bytes, _read_op),
                   stat=_absent_stat,
                   is_mounted=lambda a: True,
                   local=False)
    search = _search_command({'room': _room_searcher}, io, guard=True)
    with pytest.raises(FileNotFoundError):
        asyncio.run(
            search(FakeAccessor(), [spec("/rooms/red")], ["ada"],
                   CommandOpts()))


def test_stream_first_pull_failure_falls_back_to_bytes():
    # A native stream that refuses a kind before yielding (mongodb's
    # documents-only stream on schema.json) must not fail the scan.
    async def _refusing_stream(accessor: FakeAccessor,
                               path: PathSpec,
                               index=NULL_INDEX):
        raise enoent(path.virtual)
        yield b""

    io = CommandIO(readdir=_readdir_op,
                   read_bytes=_read_op,
                   read_stream=_refusing_stream,
                   stat=_stat_op,
                   is_mounted=lambda a: True,
                   local=False)
    search = _search_command({'room': _room_searcher}, io, stream=True)
    out, result = asyncio.run(
        search(FakeAccessor(), [spec("/rooms/red/a.json")], ["ada"],
               CommandOpts()))
    assert result.exit_code == 0
    assert b"x ada" in asyncio.run(_drain(out))


def test_stream_failure_after_data_propagates():

    async def _breaking_stream(accessor: FakeAccessor,
                               path: PathSpec,
                               index=NULL_INDEX):
        yield CONTENT
        raise enoent(path.virtual)

    io = CommandIO(readdir=_readdir_op,
                   read_bytes=_read_op,
                   read_stream=_breaking_stream,
                   stat=_stat_op,
                   is_mounted=lambda a: True,
                   local=False)
    search = _search_command({'room': _room_searcher}, io, stream=True)
    with pytest.raises(FileNotFoundError):
        out, _ = asyncio.run(
            search(FakeAccessor(), [spec("/rooms/red/a.json")], ["ada"],
                   CommandOpts()))
        asyncio.run(_drain(out))


def test_refused_pushdown_falls_back_to_the_scan():
    # A push-down past the mount's read cap cannot print its answer; the
    # scan reads the operand, which refuses the same way, and reports it
    # against the operand as typed, then moves on as grep does.
    async def _refusing_searcher(accessor: FakeAccessor, match: ScopeMatch,
                                 query: SearchQuery) -> list[str]:
        raise efbig(f"rooms/{match.slots['room']}/{match.slots['note']}")

    async def _refused_read(accessor: FakeAccessor,
                            path: PathSpec,
                            index=NULL_INDEX) -> bytes:
        raise efbig(path)

    io = replace(IO,
                 read_bytes=_refused_read,
                 read_stream=partial(stream_from_bytes, _refused_read))
    search = _search_command({'note': _refusing_searcher}, io)
    out, result = asyncio.run(
        search(FakeAccessor(), [spec("/rooms/red/a.json")], ["ada"],
               CommandOpts()))
    assert asyncio.run(_drain(out)) == b""
    assert result.exit_code == 2
    assert asyncio.run(
        result.stderr_str()) == ("grep: /h/rooms/red/a.json: File too large\n")


def test_query_carries_the_honored_flags():
    seen: list[SearchQuery] = []

    async def recorder(accessor: FakeAccessor, match: ScopeMatch,
                       query: SearchQuery) -> list[str]:
        seen.append(query)
        return ["line"]

    search = _search_command({'room': recorder}, IO)
    asyncio.run(
        search(FakeAccessor(), [spec("/rooms/red")], ["ada"],
               CommandOpts(flags={"i": True})))
    assert seen[0].options["grep"]["ignore_case"]
    assert not seen[0].options["grep"]["fixed_string"]


def test_stdin_operand_reads_the_pipe_not_the_backend():
    # A `-` operand is the line's stdin, which no backend holds. Asked
    # about it, a search that answers any operand said "no match" and
    # the pipe was never read.
    asked: list[str] = []

    async def answer_everything(accessor: FakeAccessor,
                                operand: PathSpec,
                                query: SearchQuery,
                                index=NULL_INDEX) -> list[str]:
        asked.append(operand.raw_path)
        return []

    ops = SearchOps(search=answer_everything,
                    meta={"grep": {
                        "mode": "literal",
                        "stream": False
                    }})
    dash = PathSpec(virtual="/h/-",
                    directory="/h/",
                    vfs_path="-",
                    resolved=True,
                    raw_path="-")
    for name in ("grep", "rg"):
        out, result = asyncio.run(
            run_search(replace(IO, search=ops), name, FakeAccessor(), [dash],
                       ["ada"], CommandOpts(stdin=b"x ada\n")))
        assert (asyncio.run(_drain(out)), result.exit_code) == (b"x ada\n", 0)
    assert asked == []
