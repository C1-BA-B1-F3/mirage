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

from mirage.commands.builtin.bin.io import IO
from mirage.core.bin.refuse import refuse
from mirage.ops.generic import make_generic_ops
from mirage.ops.registry import RegisteredOp

# The IO wires reads only, so the view registers no write command; each
# write op is its own refusal instead of a missing op, which would answer
# "Operation not supported" where a read-only directory says EROFS.
OPS = make_generic_ops("bin", IO) + [
    RegisteredOp(name=name, vfs="bin", filetype=None, fn=refuse, write=True)
    for name in ("write", "append", "create", "mkdir", "unlink", "rmdir",
                 "rename", "truncate", "setattr")
]
