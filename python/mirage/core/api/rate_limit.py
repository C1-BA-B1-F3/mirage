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
import time
from collections.abc import Awaitable, Callable


class RateLimiter:
    """Spaces calls that share a key to at most ``rate`` per second.

    For an API that meters requests per second per resource and answers a
    burst with a penalty window rather than a queue (Airtable allows 5 per
    base, then refuses everything for 30 seconds), spacing the calls up
    front is cheaper than any retry. Each call reserves the next free slot
    for its key before it awaits anything, so concurrent callers queue in
    arrival order and the event loop needs no lock. A caller the loop
    wakes late moves every slot behind it back by as much, so a stall
    cannot release the callers queued behind it in one burst. Slots hold
    monotonic seconds, not loop handles, so one limiter serves every loop
    in the process.

    Args:
        rate (float): calls per second allowed per key.
        clock (Callable[[], float]): monotonic seconds, injectable for
            tests.
        sleep (Callable[[float], Awaitable[None]]): the wait, injectable for
            tests.
    """

    def __init__(
        self,
        rate: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if not rate > 0:
            raise ValueError(f"rate must be positive, got {rate!r}")
        self._interval = 1.0 / rate
        self._clock = clock
        self._sleep = sleep
        self._next: dict[str, float] = {}
        self._shift: dict[str, float] = {}

    async def acquire(self, key: str) -> None:
        """Wait for this key's next slot.

        Args:
            key (str): what the server meters by (an Airtable base id).
        """
        now = self._clock()
        slot = max(now, self._next.get(key, now))
        self._next[key] = slot + self._interval
        if slot <= now:
            return
        seen = self._shift.get(key, 0.0)
        await self._sleep(slot - now)
        while (moved := self._shift.get(key, 0.0)) != seen:
            slot += moved - seen
            seen = moved
            now = self._clock()
            if slot > now:
                await self._sleep(slot - now)
        late = self._clock() - slot
        if late > 0:
            self._shift[key] = seen + late
            self._next[key] += late
