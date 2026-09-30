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
import gc
import threading
import weakref

import pytest

from mirage.io.cachable_iterator import CachableAsyncIterator
from mirage.io.types import ByteSource
from mirage.workspace.mount.activity import ActivityStream, VFSActivity


@pytest.mark.asyncio
@pytest.mark.parametrize("finish", ["eof", "error", "close", "bounded"])
async def test_vfs_usage_ends_with_its_stream(finish):
    activity = VFSActivity()

    async def chunks():
        yield b"value"
        if finish == "error":
            raise ValueError("read failed")

    source = chunks()
    if finish == "bounded":
        source = CachableAsyncIterator(source)
    source = activity.hold(source)
    waiting = asyncio.create_task(activity.wait())
    await asyncio.sleep(0)
    assert not waiting.done()
    if finish == "close":
        await source.aclose()
        await source.aclose()
    elif finish == "bounded":
        assert await source.drain_bounded(0) is None
    elif finish == "error":
        with pytest.raises(ValueError, match="read failed"):
            async for _ in source:
                pass
    else:
        assert b"".join([chunk async for chunk in source]) == b"value"
    await asyncio.wait_for(waiting, 5)
    release = activity.acquire()
    waiting = asyncio.create_task(activity.wait())
    await asyncio.sleep(0)
    assert not waiting.done()
    release()
    await asyncio.wait_for(waiting, 5)


@pytest.mark.asyncio
async def test_exhausted_cache_stream_does_not_keep_a_vfs_active():
    content = b"value"

    async def chunks():
        yield content

    cached = CachableAsyncIterator(chunks())
    assert await cached.drain() == content
    activity = VFSActivity()
    activity.hold(cached)
    await asyncio.wait_for(activity.wait(), 1)


@pytest.mark.asyncio
async def test_close_waits_for_a_pending_pull_before_releasing_usage():
    activity = VFSActivity()
    entered = asyncio.Event()
    release = asyncio.Event()

    async def chunks():
        entered.set()
        await release.wait()
        yield b"value"

    source = activity.hold(chunks())
    pulling = asyncio.create_task(source.__anext__())
    await entered.wait()
    closing = asyncio.create_task(source.aclose())
    waiting = asyncio.create_task(activity.wait())
    await asyncio.sleep(0)
    assert not closing.done()
    assert not waiting.done()
    release.set()
    assert await pulling == b"value"
    await asyncio.wait_for(asyncio.gather(closing, waiting), 1)


class _Counted:
    """A source that counts its closes and can fail its second pull.

    Args:
        fail (bool): whether the second pull raises instead of ending.
    """

    def __init__(self, fail: bool = False) -> None:
        self._fail = fail
        self.pulls = 0
        self.closes = 0

    def __aiter__(self) -> "_Counted":
        return self

    async def __anext__(self) -> bytes:
        self.pulls += 1
        if self.pulls == 1:
            return b"value"
        if self._fail:
            raise ValueError("read failed")
        raise StopAsyncIteration

    async def aclose(self) -> None:
        self.closes += 1


@pytest.mark.asyncio
async def test_a_stream_collected_unclosed_closes_its_source_then_releases():
    events: list[str] = []

    async def chunks():
        try:
            yield b"one"
            yield b"two"
        finally:
            await asyncio.sleep(0.05)
            events.append("source closed")

    stream = ActivityStream(chunks(), lambda: events.append("released"))
    assert await anext(stream) == b"one"
    del stream
    gc.collect()
    assert events == []
    for _ in range(100):
        if "released" in events:
            break
        await asyncio.sleep(0.01)
    assert events == ["source closed", "released"]


@pytest.mark.asyncio
async def test_a_held_stream_collected_unclosed_lets_the_vfs_go_idle():
    activity = VFSActivity()
    source = _Counted()
    stream = activity.hold(source)
    assert await anext(stream) == b"value"
    waiting = asyncio.create_task(activity.wait())
    await asyncio.sleep(0)
    assert not waiting.done()
    del stream
    gc.collect()
    await asyncio.wait_for(waiting, 1)
    assert source.closes == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("finish", ["eof", "error", "close"])
async def test_a_stream_released_explicitly_is_not_closed_again_when_collected(
        finish):
    released: list[bool] = []
    source = _Counted(fail=finish == "error")
    stream = ActivityStream(source, lambda: released.append(True))
    assert await anext(stream) == b"value"
    if finish == "close":
        await stream.aclose()
    elif finish == "error":
        with pytest.raises(ValueError, match="read failed"):
            await anext(stream)
    else:
        with pytest.raises(StopAsyncIteration):
            await anext(stream)
    assert released == [True]
    del stream
    gc.collect()
    await asyncio.sleep(0.01)
    assert source.closes == (1 if finish == "close" else 0)
    assert released == [True]


def test_a_stream_collected_without_a_loop_is_released_unclosed():
    released: list[bool] = []
    source = _Counted()
    stream = ActivityStream(source, lambda: released.append(True))
    del stream
    gc.collect()
    assert released == [True]
    assert source.closes == 0


@pytest.mark.asyncio
async def test_a_stream_collected_on_another_thread_stays_on_its_loop():
    loop_thread = threading.get_ident()
    events: list[tuple[str, bool]] = []

    async def chunks():
        try:
            yield b"one"
            yield b"two"
        finally:
            events.append(
                ("source closed", threading.get_ident() == loop_thread))

    stream = ActivityStream(
        chunks(), lambda: events.append(
            ("released", threading.get_ident() == loop_thread)))
    assert await anext(stream) == b"one"
    held = [stream]
    del stream
    worker = threading.Thread(target=held.clear)
    worker.start()
    worker.join()
    for _ in range(100):
        if len(events) == 2:
            break
        await asyncio.sleep(0.01)
    assert events == [("source closed", True), ("released", True)]


async def _held_through_itself(
        activity: VFSActivity,
        events: list[str]) -> weakref.ref[ActivityStream]:
    owner: list[ByteSource] = []

    async def chunks():
        try:
            yield b"one" if owner else b"zero"
            yield b"two"
        finally:
            events.append("source closed")

    stream = activity.hold(chunks())
    assert isinstance(stream, ActivityStream)
    owner.append(stream)
    assert await anext(stream) == b"one"
    return weakref.ref(stream)


@pytest.mark.asyncio
async def test_a_stream_whose_source_reaches_back_to_it_is_still_collected():
    activity = VFSActivity()
    events: list[str] = []
    alive = await _held_through_itself(activity, events)
    waiting = asyncio.create_task(activity.wait())
    gc.collect()
    await asyncio.wait_for(waiting, 1)
    assert alive() is None
    assert events == ["source closed"]
