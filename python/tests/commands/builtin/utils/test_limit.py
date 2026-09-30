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
from collections.abc import AsyncIterator

import pytest

from mirage.commands.builtin.utils.limit import (apply_limit,
                                                 maybe_with_timeout,
                                                 run_with_timeout,
                                                 with_pull_timeout,
                                                 with_timeout)
from mirage.commands.errors import CommandTimeoutError
from mirage.io.types import materialize
from mirage.types import Limit, OnExceed

_TEN = b"".join(f"line{i}\n".encode() for i in range(10))


async def _stream(data: bytes) -> AsyncIterator[bytes]:
    for i in range(0, len(data), 7):
        yield data[i:i + 7]


async def _slow_stream() -> AsyncIterator[bytes]:
    await asyncio.sleep(5)
    yield b"x"


async def _const(value):
    return value


async def _sleep_forever():
    await asyncio.sleep(5)


@pytest.mark.asyncio
async def test_no_limit_passthrough():
    out, io = await apply_limit(_TEN, None)
    assert out == _TEN and io.exit_code == 0 and io.stderr is None


@pytest.mark.asyncio
async def test_under_limit_not_truncated():
    sg = Limit(max_lines=100)
    out, io = await apply_limit(_TEN, sg)
    assert out == _TEN and io.stderr is None


@pytest.mark.asyncio
async def test_truncate_by_lines():
    sg = Limit(max_lines=3)
    out, io = await apply_limit(_TEN, sg)
    assert out == b"line0\nline1\nline2\n"
    assert io.exit_code == 0
    assert b"truncated" in (await materialize(io.stderr))


@pytest.mark.asyncio
async def test_error_by_lines():
    sg = Limit(max_lines=3, on_exceed=OnExceed.ERROR)
    out, io = await apply_limit(_TEN, sg)
    assert out is None
    assert io.exit_code == 1
    assert b"truncated" in (await materialize(io.stderr))


@pytest.mark.asyncio
async def test_truncate_by_bytes():
    sg = Limit(max_bytes=10)
    out, io = await apply_limit(_TEN, sg)
    assert out == _TEN[:10]
    assert b"truncated" in (await materialize(io.stderr))


@pytest.mark.asyncio
async def test_streaming_input_truncates_and_stops_early():
    sg = Limit(max_lines=2)
    out, io = await apply_limit(_stream(_TEN), sg)
    assert out == b"line0\nline1\n"
    assert b"truncated" in (await materialize(io.stderr))


def test_maybe_with_timeout_passthrough_when_no_limit():
    stream = _stream(_TEN)
    assert maybe_with_timeout(stream, None, "cat") is stream


def test_maybe_with_timeout_passthrough_when_bytes():
    assert maybe_with_timeout(_TEN, Limit(timeout_seconds=1), "cat") == _TEN


def test_maybe_with_timeout_passthrough_when_no_timeout():
    stream = _stream(_TEN)
    assert maybe_with_timeout(stream, Limit(max_lines=3), "cat") is stream


def test_maybe_with_timeout_passthrough_when_nonpositive():
    stream = _stream(_TEN)
    assert maybe_with_timeout(stream, Limit(timeout_seconds=0),
                              "cat") is stream


@pytest.mark.asyncio
async def test_maybe_with_timeout_wraps_and_fires():
    wrapped = maybe_with_timeout(_slow_stream(), Limit(timeout_seconds=0.1),
                                 "cat")
    with pytest.raises(CommandTimeoutError):
        await materialize(wrapped)


@pytest.mark.asyncio
async def test_run_with_timeout_returns_result_when_under_budget():
    assert await run_with_timeout(_const(42), 1.0, "sleep") == 42


@pytest.mark.asyncio
async def test_run_with_timeout_no_timeout_when_seconds_falsy():
    assert await run_with_timeout(_const(7), None, "sleep") == 7


@pytest.mark.asyncio
async def test_run_with_timeout_raises_on_overrun():
    with pytest.raises(CommandTimeoutError):
        await run_with_timeout(_sleep_forever(), 0.1, "sleep")


@pytest.mark.asyncio
@pytest.mark.parametrize("chunk_size", [1, 2, 20])
@pytest.mark.parametrize("data,limit,expected,truncated", [
    (b"a\nb\n", Limit(max_lines=2), b"a\nb\n", False),
    (b"a\nb\nc\nd\n", Limit(max_lines=2, max_bytes=7), b"a\nb\n", True),
    (b"abc", Limit(max_lines=0), b"", True),
    (b"abc", Limit(max_bytes=0), b"", True),
    (b"abc", Limit(max_bytes=3), b"abc", False),
    (b"a\nb", Limit(max_lines=1), b"a\n", True),
])
async def test_bounds_are_independent_of_chunks(chunk_size, data, limit,
                                                expected, truncated):

    async def source():
        for at in range(0, len(data), chunk_size):
            yield data[at:at + chunk_size]

    result, io = await apply_limit(source(), limit)
    assert await materialize(result) == expected
    assert ("truncated" in await io.stderr_str()) is truncated


@pytest.mark.asyncio
async def test_limit_closes_its_source_when_output_is_cut():
    closed = False

    async def source():
        nonlocal closed
        try:
            yield b"a\nb\nc\n"
            pytest.fail("a capped reader must not request another chunk")
        finally:
            closed = True

    result, io = await apply_limit(source(), Limit(max_lines=1))
    assert await materialize(result) == b"a\n"
    assert closed


class _Paced:
    """A source that waits before each chunk and records its close.

    Args:
        delays (list[float]): seconds to wait before each chunk.
    """

    def __init__(self, delays: list[float]):
        self._delays = list(delays)
        self.pulls = 0
        self.closed = False

    def __aiter__(self) -> "_Paced":
        return self

    async def __anext__(self) -> bytes:
        if self.pulls >= len(self._delays):
            raise StopAsyncIteration
        delay = self._delays[self.pulls]
        self.pulls += 1
        await asyncio.sleep(delay)
        return f"c{self.pulls}".encode()

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_with_pull_timeout_raises_when_one_pull_overruns():
    source = _Paced([0, 5])
    paced = with_pull_timeout(source, 0.05, "read")
    assert await anext(paced) == b"c1"
    with pytest.raises(CommandTimeoutError):
        await anext(paced)
    assert source.closed


@pytest.mark.asyncio
async def test_with_pull_timeout_passes_fast_pulls_past_the_total_budget():
    source = _Paced([0.02] * 5)
    paced = with_pull_timeout(source, 0.05, "read")
    assert [chunk
            async for chunk in paced] == [b"c1", b"c2", b"c3", b"c4", b"c5"]


@pytest.mark.asyncio
@pytest.mark.parametrize("finish", ["eof", "close"])
async def test_with_pull_timeout_closes_its_source_at_the_end(finish):
    source = _Paced([0, 0, 0])
    paced = with_pull_timeout(source, 1, "read")
    if finish == "eof":
        assert len([chunk async for chunk in paced]) == 3
    else:
        assert await anext(paced) == b"c1"
        await paced.aclose()
        assert source.pulls == 1
    assert source.closed


_HELPERS = ["run_with_timeout", "with_timeout", "with_pull_timeout"]


class _Stalls:
    """A source whose one pull waits, then raises or runs its own deadline.

    Args:
        delay (float): seconds the pull waits first.
        error (BaseException | None): what the pull raises after the
            wait; None runs a backend deadline of its own instead.
    """

    def __init__(self, delay: float, error: BaseException | None) -> None:
        self._delay = delay
        self._error = error

    def __aiter__(self) -> "_Stalls":
        return self

    async def __anext__(self) -> bytes:
        await asyncio.sleep(self._delay)
        if self._error is None:
            await asyncio.wait_for(asyncio.sleep(5), 0.01)
        else:
            raise self._error
        return b"never"


async def _pull_within(helper: str, source: _Stalls, seconds: float) -> bytes:
    if helper == "run_with_timeout":
        return await run_with_timeout(anext(source), seconds, "read")
    if helper == "with_timeout":
        return await anext(with_timeout(source, seconds, "read"))
    return await anext(with_pull_timeout(source, seconds, "read"))


@pytest.mark.asyncio
@pytest.mark.parametrize("helper", _HELPERS)
@pytest.mark.parametrize("raised", [TimeoutError, OSError])
async def test_a_backend_etimedout_inside_the_budget_keeps_its_errno(
        helper, raised):
    error = raised(errno.ETIMEDOUT, "connect timed out")
    with pytest.raises(OSError) as exc:
        await _pull_within(helper, _Stalls(0.01, error), 5)
    assert exc.value is error
    assert exc.value.errno == errno.ETIMEDOUT
    assert not isinstance(exc.value, CommandTimeoutError)


@pytest.mark.asyncio
@pytest.mark.parametrize("helper", _HELPERS)
async def test_a_backend_deadline_of_its_own_is_not_the_budget_expiring(
        helper):
    with pytest.raises(TimeoutError) as exc:
        await _pull_within(helper, _Stalls(0, None), 5)
    assert not isinstance(exc.value, CommandTimeoutError)


@pytest.mark.asyncio
@pytest.mark.parametrize("helper", _HELPERS)
async def test_an_overrun_of_the_budget_raises_command_timeout(helper):
    error = TimeoutError(errno.ETIMEDOUT, "too late")
    with pytest.raises(CommandTimeoutError) as exc:
        await _pull_within(helper, _Stalls(5, error), 0.05)
    assert exc.value.command == "read"
    assert exc.value.seconds == 0.05
    assert str(exc.value) == "read: timed out after 0.05s"
    assert isinstance(exc.value.__cause__, TimeoutError)
    assert exc.value.__cause__ is not error
