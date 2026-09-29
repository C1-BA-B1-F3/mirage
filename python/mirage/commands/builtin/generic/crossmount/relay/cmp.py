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

from mirage.commands.builtin.generic.cmp import cmp_cmd as generic_cmp
from mirage.commands.builtin.generic.cmp import parse_flags
from mirage.commands.builtin.generic.crossmount.types import CrossResult
from mirage.commands.builtin.generic.crossmount.utils import flat_scopes, relay
from mirage.commands.spec.types import FlagValue
from mirage.io.types import ByteSource
from mirage.runtime.types import DispatchFn
from mirage.types import PathSpec


async def run_cmp(scopes: list[PathSpec],
                  text_args: list[str],
                  flag_kwargs: dict[str, FlagValue],
                  dispatch: DispatchFn,
                  stdin: ByteSource | None = None) -> CrossResult:
    """Byte-compare two files on different mounts via the shared generic.

    Pure wiring: both sides are read through dispatch-relayed primitives,
    and the flags go through the generic's own ``parse_flags`` -- reading
    them a second time here is how the relay came to take ``-i`` as a
    bare int while the generic had moved on to GNU's ``SKIP1:SKIP2``.

    Args:
        scopes (list[PathSpec]): The two path operands.
        text_args (list[str]): The SKIP1 and SKIP2 operands, if any.
        flag_kwargs (dict): Flags parsed against the shared cmp spec.
        dispatch (DispatchFn): Workspace operation dispatcher.
        stdin (ByteSource | None): The line's input, which a ``-`` or
            ``/dev/stdin`` operand reads.
    """
    parsed = parse_flags(flag_kwargs)
    return await generic_cmp(flat_scopes(scopes),
                             text_args,
                             stdin=stdin,
                             read_bytes=functools.partial(
                                 relay, dispatch, "read"),
                             silent=parsed.silent,
                             verbose=parsed.verbose,
                             limit=parsed.limit,
                             print_bytes=parsed.print_bytes,
                             skip=parsed.skip)
