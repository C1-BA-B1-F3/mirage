from collections.abc import Awaitable, Callable

from mirage.commands.builtin.utils.lines import map_lines
from mirage.commands.builtin.utils.operands import (
    materialized_read,
    merge_split_errors,
    split_readable,
)
from mirage.commands.builtin.utils.stream import (
    read_stdin_async,
    stdin_stat,
    stdin_stream,
)
from mirage.commands.config import CommandOpts
from mirage.io.types import ByteSource, IOResult
from mirage.types import PathSpec, PolymorphicReadFn, StatFn


async def rev(
    paths: list[PathSpec],
    *,
    read_bytes: Callable[..., Awaitable[bytes]],
    stdin: ByteSource | None = None,
) -> tuple[ByteSource | None, IOResult]:
    if paths:
        # Each file is reversed on its own and keeps its own line ends, so
        # a last line with no newline stays without one (util-linux rev).
        parts = [
            map_lines(
                (await read_bytes(p)).decode(errors="replace"), _reversed
            )
            for p in paths
        ]
        return "".join(parts).encode(), IOResult()

    raw = await read_stdin_async(stdin) or b""
    return map_lines(
        raw.decode(errors="replace"), _reversed
    ).encode(), IOResult()


def _reversed(line: str) -> str:
    return line[::-1]


async def rev_generic(
    paths: list[PathSpec],
    texts: list[str],
    opts: CommandOpts,
    stat: StatFn,
    stream: PolymorphicReadFn,
) -> tuple[ByteSource | None, IOResult]:
    """Run rev over resolved operands; mirrors revGeneric.

    Args:
        paths (list[PathSpec]): Glob-resolved operands, empty for stdin.
        texts (list[str]): Non-path words, unused by rev.
        opts (CommandOpts): Flags and stdin from the dispatcher.
        stat (StatFn): Bound stat called as ``stat(path)``.
        stream (PolymorphicReadFn): Bound reader called as
            ``stream(path)``.
    """
    # util-linux rev opens `-` as a file; only /dev/stdin is stdin.
    stat = stdin_stat(stat, dash=False)
    stream = stdin_stream(stream, opts.stdin, dash=False)
    readable, err = await split_readable(paths, stat, "rev")
    if err and not readable:
        return None, IOResult(exit_code=1, stderr=err)
    return await merge_split_errors(
        await rev(
            readable, read_bytes=materialized_read(stream), stdin=opts.stdin
        ),
        err,
    )


__all__ = ["rev", "rev_generic"]
