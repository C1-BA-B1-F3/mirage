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

from typing import Any

# wasmtime is the `wasi` extra, so importing this package must not
# require it: every name below resolves to None when it is absent and
# each runtime raises a pointed ImportError at construction instead.
# The private `_func`/`_slab` modules are what slab.py patches; they
# load on their own so a wasmtime that moved them still runs, only
# without the lock.
wasmtime: Any
Func: Any
FuncType: Any
ValType: Any
wasmtime_func: Any
wasmtime_slab: Any
try:
    import wasmtime as _wasmtime
    from wasmtime import Func as _Func
    from wasmtime import FuncType as _FuncType
    from wasmtime import ValType as _ValType
except ImportError:
    wasmtime = None
    Func = None
    FuncType = None
    ValType = None
else:
    wasmtime = _wasmtime
    Func = _Func
    FuncType = _FuncType
    ValType = _ValType
try:
    from wasmtime import _func as _wasmtime_func
    from wasmtime import _slab as _wasmtime_slab
except ImportError:
    wasmtime_func = None
    wasmtime_slab = None
else:
    wasmtime_func = _wasmtime_func
    wasmtime_slab = _wasmtime_slab
