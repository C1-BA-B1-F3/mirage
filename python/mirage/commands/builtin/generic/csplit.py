import re
from collections.abc import Awaitable, Callable

from mirage.commands.builtin.utils.lines import split_lines
from mirage.commands.builtin.utils.stream import read_stdin_async
from mirage.io.types import ByteSource, IOResult
from mirage.types import PathSpec
from mirage.utils.errors import FS_ERRORS, fs_strerror
from mirage.utils.key_prefix import mount_key
from mirage.utils.path import resolve_path


def _split_by_patterns(
    lines: list[str],
    patterns: list[str],
    suppress_matched: bool,
) -> list[list[str]]:
    parts: list[list[str]] = []
    current_start = 0
    for pat in patterns:
        if pat.startswith("/") and pat.endswith("/"):
            regex = pat[1:-1]
            for idx in range(current_start, len(lines)):
                if re.search(regex, lines[idx]):
                    parts.append(lines[current_start:idx])
                    current_start = idx + 1 if suppress_matched else idx
                    break
        else:
            line_num = int(pat)
            split_at = line_num - 1
            if split_at > current_start:
                parts.append(lines[current_start:split_at])
                current_start = split_at
    if current_start < len(lines):
        parts.append(lines[current_start:])
    return parts


async def csplit(
    paths: list[PathSpec],
    patterns: list[str],
    *,
    read_bytes: Callable[..., Awaitable[bytes]],
    write_bytes: Callable[..., Awaitable[None]],
    stdin: ByteSource | None = None,
    prefix: str | PathSpec = "xx",
    mount_prefix: str = "",
    cwd: str = "/",
    relay: bool = False,
    digits: int = 2,
    suffix_format: str | None = None,
    keep_on_error: bool = False,
    silent: bool = False,
    suppress_matched: bool = False,
    elide_empty: bool = False,
) -> tuple[ByteSource | None, IOResult]:
    # An output is the -f prefix, or `xx` in the working directory, plus
    # its suffix, wherever the input lives: GNU writes `xx00` to the cwd,
    # names it as it formed it (`csplit: xx00`), and stops at the first
    # one it cannot create, -k or not.
    if isinstance(prefix, PathSpec):
        prefix_virtual, typed_prefix = prefix.virtual, prefix.raw_path
    else:
        prefix_virtual, typed_prefix = resolve_path(prefix, cwd), prefix
    suffix_fmt = suffix_format if suffix_format else f"%0{digits}d"
    # `-` is stdin. /dev/stdin would run csplit on the /dev mount, which
    # is where its pieces would land, so it stays a path.
    if paths and paths[0].raw_path != "-":
        raw = await read_bytes(paths[0])
    else:
        stdin_raw = await read_stdin_async(stdin)
        raw = stdin_raw if stdin_raw is not None else b""
    text = raw.decode(errors="replace")
    lines = split_lines(text)
    parts = _split_by_patterns(lines, list(patterns), suppress_matched)
    writes: dict[str, ByteSource] = {}
    sizes: list[str] = []
    stderr: bytes | None = None
    try:
        for idx, part in enumerate(parts):
            if elide_empty and not part:
                continue
            name = suffix_fmt % idx
            virtual = prefix_virtual + name
            spec = PathSpec.from_str_path(virtual,
                                          mount_key(virtual, mount_prefix))
            data = ("\n".join(part) + "\n").encode() if part else b""
            try:
                await write_bytes(spec, data)
            except FS_ERRORS as exc:
                stderr = (f"csplit: {typed_prefix + name}: "
                          f"{fs_strerror(exc)}\n").encode()
                break
            if not relay:
                # Relay writes land on whichever mount owns each path and
                # invalidate through the dispatcher; keying them here
                # would have the runner prefix them onto this mount.
                writes[spec.mount_path] = data
            sizes.append(str(len(data)))
    except Exception:
        if not keep_on_error:
            raise
    output = "" if silent or not sizes else "\n".join(sizes) + "\n"
    return output.encode(), IOResult(writes=writes,
                                     stderr=stderr,
                                     exit_code=1 if stderr else 0)


__all__ = ["csplit"]
