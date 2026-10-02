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
import logging
from collections.abc import Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager
from typing import ParamSpec, TypeVar, cast

logger = logging.getLogger(__name__)


class ConcurrencyLimiter:
    """Limit concurrent async operations within one process.

    Args:
        max_concurrency (int): Maximum number of simultaneous operations.
    """

    def __init__(self, max_concurrency: int) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        self._semaphore = asyncio.Semaphore(max_concurrency)

    def acquire(self) -> AbstractAsyncContextManager[None]:
        """Return a context manager that holds one concurrency permit."""
        return self._semaphore


_T = TypeVar("_T")
_R = TypeVar("_R")
_P = ParamSpec("_P")


async def run_blocking(
    fn: Callable[_P, _R], *args: _P.args, **kwargs: _P.kwargs
) -> _R:
    """Run blocking work off-loop, retaining ownership until its thread ends.

    Args:
        fn (Callable): synchronous operation; receives the caller's context.
        args: positional arguments to the operation.
        kwargs: keyword arguments to the operation.
    """
    worker = asyncio.create_task(asyncio.to_thread(fn, *args, **kwargs))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        try:
            await settle(worker)
        except Exception:
            logger.debug(
                "blocking operation failed during cancellation", exc_info=True
            )
        raise


async def bounded_map(
    items: Sequence[_T], fn: Callable[[_T], Awaitable[_R]], workers: int
) -> list[_R]:
    """Map in order with bounded tasks, settling every worker on failure.

    Args:
        items (Sequence): inputs in result order.
        fn (Callable): async operation for one input.
        workers (int): maximum concurrent operations, at least one.
    """
    remaining = iter(enumerate(items))
    failed = False
    results: list[_R | None] = [None] * len(items)

    async def worker() -> None:
        nonlocal failed
        try:
            for index, item in remaining:
                if failed:
                    return
                results[index] = await fn(item)
        except BaseException:
            failed = True
            raise

    tasks = [
        asyncio.create_task(worker())
        for _ in range(min(max(1, workers), len(items)))
    ]
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    return cast(list[_R], results)


async def settle(task: asyncio.Future[_R]) -> _R:
    """Wait for owned work to finish, deferring the caller's cancellation.

    Args:
        task (asyncio.Future): work that must not outlive its caller.
    """
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            logger.debug("deferring cancellation until owned work settles")
    return task.result()
