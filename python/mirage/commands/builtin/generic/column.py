from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

from mirage.commands.builtin.utils.lines import join_file_lines, split_lines
from mirage.commands.builtin.utils.stream import read_stdin_async
from mirage.commands.config import CommandOpts
from mirage.commands.spec import SPECS
from mirage.commands.spec.flag_view import FlagView
from mirage.commands.spec.types import FlagValue
from mirage.io.types import ByteSource, IOResult
from mirage.types import PathSpec


def _table_format(text: str, separator: str | None, output_sep: str) -> str:
    lines = split_lines(text)
    if not lines:
        return ""
    rows: list[list[str]] = []
    for line in lines:
        if separator:
            rows.append(line.split(separator))
        else:
            rows.append(line.split())
    if not rows:
        return ""
    max_cols = max(len(r) for r in rows)
    widths = [0] * max_cols
    for row in rows:
        for idx, cell in enumerate(row):
            if len(cell) > widths[idx]:
                widths[idx] = len(cell)
    out: list[str] = []
    for row in rows:
        parts: list[str] = []
        for idx, cell in enumerate(row):
            if idx < len(row) - 1:
                parts.append(cell.ljust(widths[idx]))
            else:
                parts.append(cell)
        out.append(output_sep.join(parts))
    return "\n".join(out) + "\n"


async def column(
    paths: list[PathSpec],
    *,
    read_bytes: Callable[..., Awaitable[bytes]],
    stdin: ByteSource | None = None,
    table: bool = False,
    separator: str | None = None,
    output_separator: str | None = None,
) -> tuple[ByteSource | None, IOResult]:
    if paths:
        # Every operand is read, as one run of lines in which a file's last
        # line ends where the next file begins.
        raw = join_file_lines([await read_bytes(p) for p in paths], b"\n")
    else:
        stdin_raw = await read_stdin_async(stdin)
        raw = stdin_raw if stdin_raw is not None else b""
    text = raw.decode(errors="replace")
    if table:
        out = _table_format(
            text, separator,
            output_separator if output_separator is not None else "  ")
    else:
        out = text
    return out.encode(), IOResult()


__all__ = ["column"]


@dataclass(frozen=True, slots=True)
class ColumnFlags:
    table: bool = False
    separator: str | None = None
    output_separator: str | None = None


def parse_flags(flags: Mapping[str, FlagValue]) -> ColumnFlags:
    fl = FlagView(flags, spec=SPECS["column"])
    return ColumnFlags(
        table=fl.as_bool("t"),
        separator=fl.as_str("s"),
        output_separator=fl.as_str("o"),
    )


async def column_generic(
    paths: list[PathSpec],
    texts: list[str],
    opts: CommandOpts,
    read_bytes: Callable[..., Awaitable[bytes]],
) -> tuple[ByteSource | None, IOResult]:
    parsed = parse_flags(opts.flags)
    return await column(paths,
                        read_bytes=read_bytes,
                        stdin=opts.stdin,
                        table=parsed.table,
                        separator=parsed.separator,
                        output_separator=parsed.output_separator)
