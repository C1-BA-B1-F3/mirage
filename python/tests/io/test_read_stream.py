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
import errno
import gc
import threading

import pytest

from mirage.commands.builtin.utils.limit import apply_op_limit
from mirage.io.read_stream import ReadStream, call_on_loop, cap_end
from mirage.types import Limit


class _Spy:
    """An async source that counts its pulls and records its close.

    Args:
        chunks (list[bytes]): what it hands out, one per pull.
        fail_at (int | None): the pull (0-based) that raises instead.
    """

    def __init__(self, chunks: list[bytes], fail_at: int | None = None):
        self._chunks = list(chunks)
        self._fail_at = fail_at
        self.pulls = 0
        self.closed = False

    def __aiter__(self) -> "_Spy":
        return self

    async def __anext__(self) -> bytes:
        at = self.pulls
        self.pulls += 1
        if self.closed or at >= len(self._chunks):
            raise StopAsyncIteration
        if at == self._fail_at:
            raise ValueError("pull failed")
        return self._chunks[at]

    async def aclose(self) -> None:
        self.closed = True


async def _opened(spy: _Spy) -> ReadStream:
    first = await anext(spy, None)
    return ReadStream(first, spy if first is not None else None)


async def _drain(stream: ReadStream) -> list[bytes]:
    return [chunk async for chunk in stream]


def test_cap_end_keeps_bytes_up_to_max_bytes():
    assert cap_end(b"abcdef", Limit(max_bytes=4), 0, 0) == 4
    assert cap_end(b"abcdef", Limit(max_bytes=4), 2, 0) == 2
    assert cap_end(b"ab", Limit(max_bytes=4), 0, 0) == 2


def test_cap_end_keeps_through_the_nth_newline_for_max_lines():
    assert cap_end(b"a\nb\nc\n", Limit(max_lines=2), 0, 0) == 4
    assert cap_end(b"a\nb\nc\n", Limit(max_lines=2), 0, 1) == 2
    assert cap_end(b"a\nbc", Limit(max_lines=2), 0, 0) == 4


def test_cap_end_with_both_caps_keeps_the_tighter():
    assert cap_end(b"a\nb\nc\n", Limit(max_bytes=3, max_lines=2), 0, 0) == 3
    assert cap_end(b"a\nb\nc\n", Limit(max_bytes=10, max_lines=1), 0, 0) == 2


def test_cap_end_is_zero_when_the_cap_is_spent():
    assert cap_end(b"abc", Limit(max_bytes=4), 4, 0) == 0
    assert cap_end(b"abc", Limit(max_bytes=4), 9, 0) == 0
    assert cap_end(b"a\nb\n", Limit(max_lines=2), 0, 2) == 0
    assert cap_end(b"a\nb\n", Limit(max_lines=0), 0, 0) == 0


_DATA = b"".join(f"row{i}\n".encode() for i in range(12))


@pytest.mark.asyncio
@pytest.mark.parametrize("split", [1, 2, 5, 7, len(_DATA)])
@pytest.mark.parametrize("limit", [
    Limit(max_bytes=0),
    Limit(max_bytes=13),
    Limit(max_bytes=len(_DATA)),
    Limit(max_bytes=len(_DATA) + 5),
    Limit(max_lines=0),
    Limit(max_lines=3),
    Limit(max_lines=12),
    Limit(max_lines=3, max_bytes=9),
    Limit(max_lines=5, max_bytes=40),
])
async def test_a_capped_stream_cuts_where_a_whole_truncate_cuts(split, limit):
    chunks = [_DATA[at:at + split] for at in range(0, len(_DATA), split)]
    stream = await _opened(_Spy(chunks))
    stream.cap(limit)
    streamed = b"".join(await _drain(stream))
    assert streamed == await apply_op_limit(_DATA, limit)


@pytest.mark.asyncio
async def test_yields_the_first_chunk_then_the_source_and_settles_once():
    spy = _Spy([b"ab", b"cde", b"f"])
    settled: list[int] = []
    stream = await _opened(spy)
    stream.on_settle(settled.append)
    assert await anext(stream) == b"ab"
    assert await anext(stream) == b"cde"
    assert await anext(stream) == b"f"
    assert settled == []
    with pytest.raises(StopAsyncIteration):
        await anext(stream)
    assert settled == [6]
    await stream.aclose()
    assert settled == [6]
    late: list[int] = []
    stream.on_settle(late.append)
    assert late == [6]


@pytest.mark.asyncio
async def test_aclose_before_eof_closes_the_source_and_settles_partial():
    spy = _Spy([b"aaaa", b"bbbb", b"cccc", b"dddd"])
    settled: list[int] = []
    stream = await _opened(spy)
    stream.on_settle(settled.append)
    assert await anext(stream) == b"aaaa"
    assert await anext(stream) == b"bbbb"
    await stream.aclose()
    assert spy.closed
    assert spy.pulls == 2
    assert settled == [8]
    with pytest.raises(StopAsyncIteration):
        await anext(stream)
    assert spy.pulls == 2
    assert settled == [8]


@pytest.mark.asyncio
async def test_a_failed_pull_settles_and_propagates_the_error():
    spy = _Spy([b"abc", b"de", b"never"], fail_at=2)
    settled: list[int] = []
    stream = await _opened(spy)
    stream.on_settle(settled.append)
    assert await anext(stream) == b"abc"
    assert await anext(stream) == b"de"
    with pytest.raises(ValueError, match="pull failed"):
        await anext(stream)
    assert settled == [5]
    with pytest.raises(StopAsyncIteration):
        await anext(stream)
    assert settled == [5]


@pytest.mark.asyncio
async def test_cap_truncation_stops_pulling_the_source():
    chunks = [bytes([65 + i]) * 10 for i in range(10)]
    spy = _Spy(chunks)
    settled: list[int] = []
    stream = await _opened(spy)
    stream.on_settle(settled.append)
    stream.cap(Limit(max_bytes=15))
    assert b"".join(await _drain(stream)) == b"".join(chunks)[:15]
    assert spy.pulls == 2
    assert spy.closed
    assert settled == [20]


@pytest.mark.asyncio
async def test_whole_is_one_chunk_and_already_settled():
    settled: list[int] = []
    stream = ReadStream.whole(b"entire")
    stream.on_settle(settled.append)
    assert settled == [6]
    assert await _drain(stream) == [b"entire"]
    assert settled == [6]


class _FailingClose(_Spy):
    """A source whose close fails after it has closed."""

    async def aclose(self) -> None:
        self.closed = True
        raise OSError(errno.EIO, "close failed")


def _fail_record(_moved: int) -> None:
    raise RuntimeError("record failed")


@pytest.mark.asyncio
async def test_a_stream_collected_unclosed_settles_with_what_it_moved():
    spy = _Spy([b"aaaa", b"bbbb", b"cccc", b"dddd"])
    settled: list[int] = []
    stream = await _opened(spy)
    stream.on_settle(settled.append)
    pulled = 0
    async for chunk in stream:
        pulled += len(chunk)
        if pulled >= 8:
            break
    assert settled == []
    del stream
    gc.collect()
    assert settled == [8]
    assert spy.pulls == 2


@pytest.mark.asyncio
async def test_a_stream_closed_and_then_collected_settles_once():
    spy = _Spy([b"ab", b"cd"])
    settled: list[int] = []
    stream = await _opened(spy)
    stream.on_settle(settled.append)
    await stream.aclose()
    del stream
    gc.collect()
    assert settled == [2]


@pytest.mark.asyncio
async def test_a_failed_settle_callback_raises_from_the_close_that_settles():
    spy = _Spy([b"ab", b"cd"])
    stream = await _opened(spy)
    stream.on_settle(_fail_record)
    with pytest.raises(RuntimeError, match="record failed"):
        await stream.aclose()
    assert spy.closed
    await stream.aclose()
    with pytest.raises(StopAsyncIteration):
        await anext(stream)


@pytest.mark.asyncio
async def test_a_failed_settle_callback_raises_from_the_pull_that_settles():
    stream = await _opened(_Spy([b"ab"]))
    stream.on_settle(_fail_record)
    assert await anext(stream) == b"ab"
    with pytest.raises(RuntimeError, match="record failed"):
        await anext(stream)
    with pytest.raises(StopAsyncIteration):
        await anext(stream)
    await stream.aclose()


@pytest.mark.asyncio
async def test_a_failed_source_close_raises_once_and_still_settles():
    spy = _FailingClose([b"ab", b"cd"])
    settled: list[int] = []
    stream = await _opened(spy)
    stream.on_settle(settled.append)
    with pytest.raises(OSError, match="close failed") as exc:
        await stream.aclose()
    assert exc.value.errno == errno.EIO
    assert spy.closed
    assert settled == [2]
    await stream.aclose()
    assert settled == [2]


async def _until(done, rounds: int = 100) -> None:
    for _ in range(rounds):
        if done():
            return
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_call_on_loop_hands_a_foreign_thread_over_to_the_loop():
    loop = asyncio.get_running_loop()
    ran: list[int] = []
    worker = threading.Thread(target=call_on_loop,
                              args=(loop,
                                    lambda: ran.append(threading.get_ident())))
    worker.start()
    worker.join()
    await _until(lambda: bool(ran))
    assert ran == [threading.get_ident()]


def test_call_on_loop_runs_in_place_once_the_loop_is_gone():
    loop = asyncio.new_event_loop()
    loop.close()
    ran: list[bool] = []
    call_on_loop(loop, lambda: ran.append(True))
    assert ran == [True]


@pytest.mark.asyncio
async def test_a_stream_collected_on_another_thread_settles_on_its_loop():
    loop_thread = threading.get_ident()
    stream = await _opened(_Spy([b"a", b"b"]))
    settled: list[tuple[int, bool]] = []
    stream.on_settle(lambda moved: settled.append(
        (moved, threading.get_ident() == loop_thread)))
    held = [stream]
    del stream
    worker = threading.Thread(target=held.clear)
    worker.start()
    worker.join()
    await _until(lambda: bool(settled))
    assert settled == [(1, True)]


@pytest.mark.asyncio
async def test_a_failing_settle_callback_does_not_skip_the_rest():
    stream = await _opened(_Spy([b"a", b"b"]))
    seen: list[int] = []

    def broken(moved: int) -> None:
        raise ValueError("broken callback")

    stream.on_settle(broken)
    stream.on_settle(seen.append)
    with pytest.raises(ValueError, match="broken callback"):
        await stream.aclose()
    assert seen == [1]


@pytest.mark.asyncio
@pytest.mark.parametrize("limit, chunks, kept", [
    (Limit(max_bytes=4), [b"abcd", b"efgh"], [b"abcd"]),
    (Limit(max_lines=1), [b"a\n", b"b\n"], [b"a\n"]),
    (Limit(max_bytes=10, max_lines=1), [b"a\n", b"bc"], [b"a\n"]),
])
async def test_a_cap_met_at_a_chunk_end_closes_without_pulling_again(
        limit, chunks, kept):
    spy = _Spy(chunks)
    stream = await _opened(spy)
    stream.cap(limit)
    assert await _drain(stream) == kept
    assert spy.pulls == 1
    assert spy.closed


class _Stalled(_Spy):
    """A source whose pulls after the first never answer."""

    async def __anext__(self) -> bytes:
        if self.pulls:
            await asyncio.Event().wait()
        return await super().__anext__()


@pytest.mark.asyncio
async def test_a_spent_cap_ends_the_read_without_waiting_on_the_backend():
    spy = _Stalled([b"abcd", b"efgh"])
    stream = await _opened(spy)
    stream.cap(Limit(max_bytes=4))
    assert await asyncio.wait_for(_drain(stream), 1) == [b"abcd"]
    assert spy.closed
