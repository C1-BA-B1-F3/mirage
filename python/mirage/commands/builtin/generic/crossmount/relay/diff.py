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

import functools

from mirage.commands.builtin.generic.crossmount.types import CrossResult
from mirage.commands.builtin.generic.crossmount.utils import flat_scopes, relay
from mirage.commands.builtin.generic.diff import diff as generic_diff
from mirage.commands.builtin.generic.diff import parse_flags
from mirage.commands.spec.types import FlagValue
from mirage.io.types import ByteSource
from mirage.runtime.types import DispatchFn
from mirage.types import PathSpec


async def run_diff(scopes: list[PathSpec],
                   flag_kwargs: dict[str, FlagValue],
                   dispatch: DispatchFn,
                   stdin: ByteSource | None = None) -> CrossResult:
    """Diff two files on different mounts via the shared generic diff.

    Pure wiring: both sides are read through dispatch-relayed primitives.

    Args:
        scopes (list[PathSpec]): The two path operands.
        flag_kwargs (dict): Flags parsed against the shared diff spec.
        dispatch (DispatchFn): Workspace operation dispatcher.
        stdin (ByteSource | None): The line's input, which a ``-`` or
            ``/dev/stdin`` operand reads.
    """
    p = functools.partial
    parsed = parse_flags(flag_kwargs)
    return await generic_diff(flat_scopes(scopes),
                              stdin=stdin,
                              read_bytes=p(relay, dispatch, "read"),
                              readdir_fn=p(relay, dispatch, "readdir"),
                              stat_fn=p(relay, dispatch, "stat"),
                              i=parsed.ignore_case,
                              w=parsed.ignore_all_space,
                              b=parsed.ignore_space_change,
                              e=parsed.ed,
                              u=parsed.unified,
                              q=parsed.brief,
                              r=parsed.recursive,
                              context=parsed.context)
