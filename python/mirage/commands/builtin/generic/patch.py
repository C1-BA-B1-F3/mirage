import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

from mirage.commands.builtin.utils.lines import split_lines
from mirage.commands.builtin.utils.stream import read_stdin_async
from mirage.commands.config import CommandOpts
from mirage.commands.spec import SPECS
from mirage.commands.spec.flag_view import FlagView
from mirage.commands.spec.types import CommandName, FlagValue
from mirage.commands.spec.usage import extra_operand_error
from mirage.io.types import ByteSource, IOResult
from mirage.types import PathSpec
from mirage.utils.errors import FS_ERRORS, READ_FAILURES, fs_strerror
from mirage.utils.quote import shell_quote


def _strip_path(path: str, strip_count: int) -> str:
    parts = path.split("/")
    return "/".join(
        parts[strip_count:]) if strip_count < len(parts) else parts[-1]


def _apply_hunks(original_lines: list[str],
                 hunks: list[tuple[int, list[str]]],
                 forward_only: bool = False) -> list[str]:
    result: list[str] = []
    src_idx = 0
    for start_line, hunk_lines in hunks:
        hunk_start = start_line - 1
        while src_idx < hunk_start and src_idx < len(original_lines):
            result.append(original_lines[src_idx])
            src_idx += 1
        if forward_only:
            expected = [
                hl[1:] for hl in hunk_lines
                if hl.startswith(" ") or hl.startswith("-")
            ]
            actual = original_lines[src_idx:src_idx + len(expected)]
            if expected != actual:
                for _ in expected:
                    if src_idx < len(original_lines):
                        result.append(original_lines[src_idx])
                        src_idx += 1
                continue
        for hl in hunk_lines:
            if hl.startswith(" "):
                result.append(hl[1:])
                src_idx += 1
            elif hl.startswith("-"):
                src_idx += 1
            elif hl.startswith("+"):
                result.append(hl[1:])
    while src_idx < len(original_lines):
        result.append(original_lines[src_idx])
        src_idx += 1
    return result


def _parse_patch(patch_text: str,
                 strip_count: int) -> dict[str, list[tuple[int, list[str]]]]:
    files: dict[str, list[tuple[int, list[str]]]] = {}
    current_file: str | None = None
    current_hunks: list[tuple[int, list[str]]] = []
    current_hunk_lines: list[str] = []
    current_start = 0

    for line in split_lines(patch_text):
        if line.startswith("--- "):
            continue
        if line.startswith("+++ "):
            if current_file and current_hunk_lines:
                current_hunks.append((current_start, current_hunk_lines))
            if current_file:
                files[current_file] = current_hunks
            raw_path = line[4:].split("\t")[0].strip()
            current_file = "/" + _strip_path(raw_path, strip_count).lstrip("/")
            current_hunks = []
            current_hunk_lines = []
            continue
        m = re.match(r"@@ -([0-9]+)", line)
        if m:
            if current_hunk_lines:
                current_hunks.append((current_start, current_hunk_lines))
            current_start = int(m.group(1))
            current_hunk_lines = []
            continue
        if current_file and (line.startswith("+") or line.startswith("-")
                             or line.startswith(" ")):
            current_hunk_lines.append(line)

    if current_file and current_hunk_lines:
        current_hunks.append((current_start, current_hunk_lines))
    if current_file:
        files[current_file] = current_hunks

    return files


def _reverse_hunks(
        hunks: list[tuple[int, list[str]]]) -> list[tuple[int, list[str]]]:
    out: list[tuple[int, list[str]]] = []
    for start, hunk_lines in hunks:
        reversed_lines: list[str] = []
        for hl in hunk_lines:
            if hl.startswith("+"):
                reversed_lines.append("-" + hl[1:])
            elif hl.startswith("-"):
                reversed_lines.append("+" + hl[1:])
            else:
                reversed_lines.append(hl)
        out.append((start, reversed_lines))
    return out


async def _load_patch_data(
    source: PathSpec | None,
    stdin: ByteSource | None,
    read_bytes: Callable[..., Awaitable[bytes]],
) -> bytes | str:
    """The patch text, or GNU's fatal line when it cannot be had.

    GNU opens the patch file before anything else and gives up on the
    whole run when it cannot (exit 2): an open that fails names the file
    (``Can't open patch file x : ...``), a read that fails does not
    (``read error : ...``), since only one patch file is ever read.

    Args:
        source (PathSpec | None): the patch file, None for stdin.
        stdin (ByteSource | None): standard input.
        read_bytes (Callable): bound reader.
    """
    if source is None:
        data = await read_stdin_async(stdin)
        return b"" if data is None else data
    try:
        return await read_bytes(source)
    except READ_FAILURES as exc:
        return f"patch: **** read error : {fs_strerror(exc)}\n"
    except FS_ERRORS as exc:
        label = shell_quote(source.raw_path or source.virtual)
        return (f"patch: **** Can't open patch file {label} : "
                f"{fs_strerror(exc)}\n")


async def patch(
    paths: list[PathSpec],
    *,
    read_bytes: Callable[..., Awaitable[bytes]],
    write_bytes: Callable[..., Awaitable[None]],
    has_vfs: bool,
    stdin: ByteSource | None = None,
    p: str | None = None,
    R: bool = False,
    i: PathSpec | None = None,
    N: bool = False,
    mount_prefix: str = "",
) -> tuple[ByteSource | None, IOResult]:
    if len(paths) > 2:
        raise extra_operand_error(CommandName.PATCH, paths[2].raw_path
                                  or paths[2].virtual)
    strip_count = int(p) if p else 0
    # `patch [ORIGFILE [PATCHFILE]]`: the second operand is the patch
    # file, ahead of -i, and the first is the one file every hunk goes to
    # in place of the names the patch's headers carry.
    source = paths[1] if len(paths) > 1 else i
    patch_data = await _load_patch_data(source if has_vfs else None, stdin,
                                        read_bytes)
    if isinstance(patch_data, str):
        return None, IOResult(exit_code=2, stderr=patch_data.encode())
    patch_text = patch_data.decode(errors="replace")
    file_hunks = _parse_patch(patch_text, strip_count)
    orig = paths[0] if paths else None
    writes: dict[str, ByteSource] = {}
    lines: list[str] = []
    for file_path, hunks in file_hunks.items():
        if orig is not None:
            file_spec, shown = orig, orig.raw_path or orig.virtual
        else:
            file_spec = PathSpec.from_str_path(
                mount_prefix.rstrip("/") + "/" + file_path.lstrip("/"),
                file_path.lstrip("/"))
            shown = file_path.lstrip("/")
        lines.append(f"patching file {shown}\n")
        try:
            original = (await read_bytes(file_spec)).decode(errors="replace")
        except FileNotFoundError:
            original = ""
        original_lines = split_lines(original)
        if R:
            hunks = _reverse_hunks(hunks)
        patched_lines = _apply_hunks(original_lines, hunks, forward_only=N)
        patched_data = ("\n".join(patched_lines) + "\n").encode()
        await write_bytes(file_spec, patched_data)
        writes[file_spec.mount_path] = patched_data
    out = "".join(lines).encode() if lines else None
    return out, IOResult(writes=writes)


__all__ = ["patch"]


@dataclass(frozen=True, slots=True)
class PatchFlags:
    strip: str | None = None
    reverse: bool = False
    input_path: PathSpec | None = None
    forward: bool = False


def parse_flags(flags: Mapping[str, FlagValue]) -> PatchFlags:
    fl = FlagView(flags, spec=SPECS["patch"])
    input_flag = fl.raw("i")
    return PatchFlags(
        strip=fl.as_str("p"),
        reverse=fl.as_bool("R"),
        input_path=input_flag if isinstance(input_flag, PathSpec) else None,
        forward=fl.as_bool("N"),
    )


async def patch_generic(
    paths: list[PathSpec],
    texts: list[str],
    opts: CommandOpts,
    read_bytes: Callable[..., Awaitable[bytes]],
    write_bytes: Callable[..., Awaitable[None]],
    has_vfs: bool,
) -> tuple[ByteSource | None, IOResult]:
    parsed = parse_flags(opts.flags)
    return await patch(paths,
                       read_bytes=read_bytes,
                       write_bytes=write_bytes,
                       has_vfs=has_vfs,
                       stdin=opts.stdin,
                       p=parsed.strip,
                       R=parsed.reverse,
                       i=parsed.input_path,
                       N=parsed.forward,
                       mount_prefix=opts.mount_prefix or "")
