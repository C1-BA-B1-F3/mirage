from functools import partial

from mirage.commands.builtin.generic.crossmount.types import CrossResult
from mirage.commands.builtin.generic.crossmount.utils import (_relay_write,
                                                              flat_scopes,
                                                              read_file)
from mirage.commands.builtin.generic.sort import sort as generic_sort
from mirage.commands.spec.types import FlagValue
from mirage.io.types import ByteSource, IOResult
from mirage.runtime.types import DispatchFn
from mirage.types import PathSpec


async def run_sort(scopes: list[PathSpec], flags: dict[str, FlagValue],
                   dispatch: DispatchFn,
                   stdin: ByteSource | None) -> CrossResult:
    """Sort independent inputs through the same generic on every mount.

    Args:
        scopes (list[PathSpec]): Expanded operands in command-line order.
        flags (dict[str, FlagValue]): Parsed options.
        dispatch (DispatchFn): Workspace operation dispatcher.
        stdin (ByteSource | None): Shared standard input cursor.
    """

    reads = IOResult()

    async def write_file(path: PathSpec, data: bytes) -> None:
        await _relay_write(dispatch, path, data)
        # A replacement must cache the new bytes, not its earlier input.
        reads.reads.pop(path.virtual, None)

    body, io = await generic_sort(flat_scopes(scopes),
                                  read_bytes=partial(read_file, dispatch,
                                                     reads),
                                  write_bytes=write_file,
                                  stdin=stdin,
                                  flags=flags)
    return body, await reads.merge(io)
