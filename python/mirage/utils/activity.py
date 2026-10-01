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
from collections.abc import Callable


class Activity:
    """Work in flight on one resource, awaited before it is released."""

    def __init__(self) -> None:
        self._count = 0
        self._idle = asyncio.Event()
        self._idle.set()

    def acquire(self) -> Callable[[], None]:
        self._count += 1
        self._idle.clear()
        released = False

        def release() -> None:
            nonlocal released
            if released:
                return
            released = True
            self._count -= 1
            if self._count == 0:
                self._idle.set()

        return release

    async def wait(self) -> None:
        await self._idle.wait()
