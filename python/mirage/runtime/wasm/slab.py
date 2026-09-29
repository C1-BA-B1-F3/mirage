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

import threading
from typing import Any

wasmtime_func: Any
wasmtime_slab: Any
try:
    from wasmtime import _func as _wasmtime_func
    from wasmtime import _slab as _wasmtime_slab
except ImportError:
    wasmtime_func = None
    wasmtime_slab = None
else:
    wasmtime_func = _wasmtime_func
    wasmtime_slab = _wasmtime_slab

_INSTALL_LOCK = threading.Lock()
_installed = False


class LockedSlab:
    """wasmtime-py's host-callback slab behind a lock.

    wasmtime-py parks every host callback in one process-wide slab and
    hands out its slots with no lock. Each wasm run is on its own worker
    thread, so two runs installing their imports at once can write two
    callbacks into one slot (one run's import then calls the other
    run's filesystem) or leave a callback where the free list keeps an
    index, after which every later run in the process fails.

    A slot is freed by the destructor wasmtime hands Rust, which fires
    wherever the run's store drops, including inside a garbage
    collection on a thread that is already in the middle of a slab
    change. The lock is reentrant, so that free gets in; it is queued
    and applied before the thread lets go of the lock. A free on
    another thread waits for the lock, so no slot is left queued once
    the lock is free.

    Args:
        inner (Any): the ``wasmtime._slab.Slab`` whose slots stay in use.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self._lock = threading.RLock()
        self._busy = False
        self._deferred: list[int] = []

    def allocate(self, val: tuple[Any, ...]) -> int:
        """Park one callback and return its slot.

        Args:
            val (tuple[Any, ...]): the callback, its result types and
                whether it takes the caller.
        """
        with self._lock:
            self._busy = True
            try:
                idx: int = self._inner.allocate(val)
            finally:
                self._settle()
            return idx

    def get(self, idx: int) -> tuple[Any, ...]:
        """The callback parked in one slot.

        Args:
            idx (int): the slot.
        """
        val: tuple[Any, ...] = self._inner.get(idx)
        return val

    def deallocate(self, idx: int) -> None:
        """Free one slot, or queue it when this thread is mid-change.

        Args:
            idx (int): the slot.
        """
        with self._lock:
            if self._busy:
                self._deferred.append(idx)
                return
            self._busy = True
            try:
                self._inner.deallocate(idx)
            finally:
                self._settle()

    def _settle(self) -> None:
        while True:
            while self._deferred:
                self._inner.deallocate(self._deferred.pop())
            self._busy = False
            if not self._deferred:
                return
            self._busy = True


def install_slab_lock() -> None:
    """Put wasmtime-py's host-callback slab behind a ``LockedSlab``.

    Once per process, before the first callback is created. It stands
    down when wasmtime is absent or when its slab module imports
    ``threading``, the sign that wasmtime-py guards the slab itself.
    """
    global _installed
    if _installed or wasmtime_func is None:
        return
    with _INSTALL_LOCK:
        if _installed:
            return
        if not hasattr(wasmtime_slab, "threading"):
            wasmtime_func.FUNCTIONS = LockedSlab(wasmtime_func.FUNCTIONS)
        _installed = True
