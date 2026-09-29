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

import logging

from mirage.commands.builtin.generic.crossmount.types import (Cmd, CrossResult,
                                                              RunSingle)
from mirage.commands.builtin.generic.crossmount.utils import (
    merge_operand_ios, relay, run_operands)
from mirage.commands.builtin.generic.wc import (WCCounts, format_count_rows,
                                                number_width, parse_flags)
from mirage.commands.builtin.utils.stream import is_stdin
from mirage.commands.errors import UsageError
from mirage.commands.spec.types import FlagValue
from mirage.io.types import IOResult
from mirage.runtime.types import DispatchFn
from mirage.types import FileType, PathSpec
from mirage.utils.errors import FS_ERRORS

logger = logging.getLogger(__name__)

# GNU prints a row's counts in this order whichever flags ask for them.
COLUMNS = ("lines", "words", "chars", "bytes_", "max_line_length")


def parse_row(line: str, columns: list[str]) -> tuple[WCCounts, str | None]:
    """Read one rendered wc row back into its counts and its label.

    Args:
        line (str): The row, counts right-aligned then one space and the
            label, which is kept whole, spaces included.
        columns (list[str]): The ``WCCounts`` fields the row shows.
    """
    rest = line
    values: dict[str, int] = {}
    for column in columns:
        number, _, rest = rest.lstrip(" ").partition(" ")
        values[column] = int(number)
    return WCCounts(**values), rest or None


async def operand_size(dispatch: DispatchFn, path: PathSpec,
                       counts: list[int]) -> int | None:
    """The size GNU sizes the columns by, which it takes from fstat.

    A stream or a directory has none. A file whose size ``stat`` cannot
    give without rendering it, or that is gone by the time it is sized,
    counts as its widest count, a lower bound, which is the width a
    count-only mount pads to on its own.

    Args:
        dispatch (DispatchFn): Workspace operation dispatcher.
        path (PathSpec): The operand the row counts.
        counts (list[int]): The counts the row shows.
    """
    if is_stdin(path):
        return None
    try:
        info = await relay(dispatch, "stat", path)
    except FS_ERRORS as exc:
        # Gone since its mount counted it: the width is only layout, so
        # the counts already taken still print, padded to the lower bound.
        logger.debug("wc: sizing %s failed: %s", path.virtual, exc)
        return max(counts)
    if info.type is FileType.DIRECTORY:
        return None
    return info.size if info.size is not None else max(counts)


async def run_wc(scopes: list[PathSpec], flag_kwargs: dict[str, FlagValue],
                 dispatch: DispatchFn, run_single: RunSingle) -> CrossResult:
    """Count each operand on its own mount and lay the rows out together.

    Each operand runs through its owning mount's ``wc``, so a mount that
    counts without reading its file (a database row count) still does,
    and reading mounts stream. Only the layout spans the line: the rows
    go through the generic's formatter with GNU's column width.

    Args:
        scopes (list[PathSpec]): Expanded operands in command-line order.
        flag_kwargs (dict): Parsed wc flags.
        dispatch (DispatchFn): Workspace operation dispatcher, for sizes.
        run_single (RunSingle): Single-mount runner for each operand.
    """
    try:
        flags = parse_flags(flag_kwargs)
    except UsageError as exc:
        return None, IOResult(exit_code=exc.exit_code,
                              stderr=(str(exc) + "\n").encode())
    except ValueError as exc:
        return None, IOResult(exit_code=1, stderr=(str(exc) + "\n").encode())
    columns = [c for c in COLUMNS if getattr(flags, c)]
    columns = columns or ["lines", "words", "bytes_"]
    runs = await run_operands(run_single, Cmd.WC, scopes, [], {
        **flag_kwargs, "total": "never"
    })
    rows: list[tuple[WCCounts, str | None]] = []
    sizes: list[int | None] = []
    totals = WCCounts()
    for run in runs:
        # One concrete operand per run, so its output is one row or none;
        # the row is taken whole, whatever its name holds.
        text = run.data.decode(errors="replace").removesuffix("\n")
        if not text:
            continue
        counts, label = parse_row(text, columns)
        rows.append((counts, label))
        values = [getattr(counts, c) for c in columns]
        sizes.append(await operand_size(dispatch, run.scope, values))
        totals.merge(counts)
    width = number_width(sizes, len(scopes), len(columns))
    body = format_count_rows(rows, totals, len(scopes), flags, width)
    return body, await merge_operand_ios(runs,
                                         max(run.io.exit_code for run in runs))
