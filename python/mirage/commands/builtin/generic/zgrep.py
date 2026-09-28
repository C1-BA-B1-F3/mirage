import re
from collections.abc import (AsyncIterator, Awaitable, Callable, Mapping,
                             Sequence)
from dataclasses import dataclass
from functools import partial

from mirage.commands.builtin.generic.decompress import open_gzip_input
from mirage.commands.builtin.grep_offsets import (decode_line, line_offsets,
                                                  match_offset, prefix_of)
from mirage.commands.builtin.grep_pattern import (compile_pattern,
                                                  resolve_pattern)
from mirage.commands.builtin.utils.constants import STDIN_OPERAND
from mirage.commands.builtin.utils.lines import split_lines
from mirage.commands.builtin.utils.links import LinkDoor
from mirage.commands.builtin.utils.operands import normalized_read
from mirage.commands.builtin.utils.output import format_records
from mirage.commands.builtin.utils.stream import (is_stdin, operand_label,
                                                  stdin_bytes)
from mirage.commands.spec import SPECS
from mirage.commands.spec.flag_view import FlagView
from mirage.commands.spec.types import FlagValue
from mirage.io.types import ByteSource, IOResult, materialize
from mirage.types import PathSpec, StatFn
from mirage.utils.compress import gunzip_partial


async def _read_plain(
    read_bytes: Callable[..., Awaitable[bytes]],
    path: PathSpec,
) -> bytes:
    return await read_bytes(path)


def _zgrep_search(
    data: bytes,
    pattern: re.Pattern[str],
    invert: bool,
    count: bool,
    line_numbers: bool,
    filename: str | None,
    only_matching: bool,
    max_count: int | None,
    byte_offsets: bool = False,
) -> tuple[list[str], bool]:
    """The lines zgrep prints for one decompressed input.

    Args:
        data (bytes): the decompressed input.
        pattern (re.Pattern[str]): the matcher grep compiles, -i folded in.
        invert (bool): -v.
        count (bool): -c, answer with the count alone.
        line_numbers (bool): -n.
        filename (str | None): the label each line carries, if any.
        only_matching (bool): -o.
        max_count (int | None): -m.
        byte_offsets (bool): -b, the byte offset of each line's start
            or, under -o, of the match itself, in the field order GNU
            grep prints (name, line, byte).
    """
    lines = split_lines(decode_line(data))
    offsets = line_offsets(lines) if byte_offsets else []
    matched: list[tuple[int, int, str]] = []
    for idx, line in enumerate(lines, 1):
        start = offsets[idx - 1] if byte_offsets else 0
        if only_matching and not invert:
            hits = list(pattern.finditer(line))
            if hits:
                for m in hits:
                    matched.append((idx, match_offset(start, line,
                                                      m.start()), m.group()))
                    if max_count is not None and len(matched) >= max_count:
                        break
        else:
            hit = bool(pattern.search(line))
            if invert:
                hit = not hit
            if hit:
                matched.append((idx, start, line))
        if max_count is not None and len(matched) >= max_count:
            break
    if count:
        value = str(len(matched))
        if filename:
            value = f"{filename}:{value}"
        return [value], len(matched) > 0
    result: list[str] = []
    for idx, offset, line in matched:
        prefix = filename + ":" if filename else ""
        prefix += prefix_of(idx if line_numbers else None,
                            offset if byte_offsets else None)
        result.append(prefix + line)
    return result, len(matched) > 0


def _files_only_match(data: bytes, pattern: re.Pattern[str],
                      invert: bool) -> bool:
    text = decode_line(data)
    for line in split_lines(text):
        hit = bool(pattern.search(line))
        if invert:
            hit = not hit
        if hit:
            return True
    return False


@dataclass(frozen=True, slots=True)
class ZgrepFlags:
    """Parsed zgrep flags; the complete set zgrep honors."""
    ignore_case: bool
    invert: bool
    count: bool
    files_only: bool
    files_without_match: bool
    line_numbers: bool
    byte_offsets: bool
    fixed: bool
    basic_regexp: bool
    force_filename: bool
    suppress_filename: bool
    only_matching: bool
    quiet: bool
    whole_word: bool
    max_count: int | None


def parse_flags(fl: FlagView, never_match: bool) -> ZgrepFlags:
    """Convert the raw flag bag into ZgrepFlags, the only string-keyed reads.

    Args:
        fl (FlagView): spec-validated view over the raw flag kwargs.
        never_match (bool): zero-pattern sentinel from resolve_pattern; it is
            a regex, so it suppresses -F.
    """
    # -l and -L set one mode in grep, so the later one on the line wins.
    listing: str | None = None
    for name in fl.typed_order("args_l", "files_without_match"):
        if fl.as_bool(name):
            listing = name
    return ZgrepFlags(
        ignore_case=fl.as_bool("i"),
        invert=fl.as_bool("v"),
        count=fl.as_bool("c"),
        files_only=listing == "args_l",
        files_without_match=listing == "files_without_match",
        line_numbers=fl.as_bool("n"),
        byte_offsets=fl.as_bool("byte_offset"),
        fixed=fl.as_bool("F") and not never_match,
        # zgrep is grep over decompressed bytes, so it reads a basic
        # expression unless -E says otherwise; -G asks for the default.
        basic_regexp=not fl.as_bool("E"),
        force_filename=fl.as_bool("H"),
        suppress_filename=fl.as_bool("h"),
        only_matching=fl.as_bool("o"),
        quiet=fl.as_bool("q"),
        whole_word=fl.as_bool("w"),
        max_count=fl.as_int("m"),
    )


async def _gunzipped(p: PathSpec, source: Callable[[PathSpec],
                                                   AsyncIterator[bytes]],
                     stat: StatFn | None, door: LinkDoor | None,
                     errors: list[str]) -> tuple[bytes, bool]:
    """One operand as ``gzip -cdfq`` hands it to zgrep's grep.

    gzip opens the name as it would under -c and -f: a missing one is
    retried with each suffix, a link is followed, and a directory is a
    warning -q keeps quiet, so grep reads nothing from it. A failed open
    is reported in gzip's words and grep still reads its empty output,
    which is why -c counts 0 there and -L lists it. The input is
    decoded with pass-through, the bytes after a member too.

    Returns what grep reads, and whether gzip failed (exit 2 for
    zgrep); a gzip warning is not a failure.

    Args:
        p (PathSpec): the operand.
        source (Callable): reads a name on the operand's mount.
        stat (StatFn | None): the mount's stat.
        door (LinkDoor | None): the namespace's links.
        errors (list[str]): collects gzip's lines.
    """
    failed = False

    def report(line: str, code: int, warning: bool) -> None:
        nonlocal failed
        if not warning:
            errors.append(line)
            failed = failed or code == 1

    opened = await open_gzip_input(p,
                                   source,
                                   report,
                                   follow=True,
                                   stat=stat,
                                   door=door)
    raw = b"" if opened is None else await materialize(opened.stream)
    data, failure = gunzip_partial(raw, passthrough=True)
    if failure is not None and failure.exit_code != 2:
        name = opened.name if opened is not None else p
        errors.append(failure.render(operand_label(name, "stdin")))
        failed = True
    return data, failed


async def zgrep(
    paths: list[PathSpec],
    texts: Sequence[str] = (),
    flags: Mapping[str, FlagValue] | None = None,
    *,
    read_bytes: Callable[..., Awaitable[bytes]],
    stdin: ByteSource | None = None,
    stat: StatFn | None = None,
    door: LinkDoor | None = None,
) -> tuple[ByteSource | None, IOResult]:
    fl = FlagView(flags, spec=SPECS["zgrep"])
    pattern, never_match = await resolve_pattern(
        texts, fl, partial(_read_plain, read_bytes),
        "zgrep: usage: zgrep [flags] pattern [path]")
    f = parse_flags(fl, never_match)
    # GNU grep 3.11 skips regex validation and selection under -m0.
    compiled = (None if f.max_count == 0 else compile_pattern(
        pattern, f.ignore_case, f.fixed, f.whole_word, f.basic_regexp))
    multi = len(paths) > 1
    show_filename = f.force_filename or (multi and not f.suppress_filename)
    any_match = False
    all_results: list[str] = []
    read = stdin_bytes(read_bytes, stdin)
    source = normalized_read(read_bytes)

    errors: list[str] = []
    failed = False
    for p in paths or [STDIN_OPERAND]:
        # zgrep decompresses each operand with `gzip -cdfq -- FILE`,
        # which reports its own failures and hands grep what it decoded.
        if is_stdin(p):
            data, failure = gunzip_partial(await read(p), passthrough=True)
            if failure is not None and failure.exit_code != 2:
                errors.append(failure.render(operand_label(p, "stdin")))
                failed = True
        else:
            data, gzip_failed = await _gunzipped(p, source, stat, door, errors)
            failed = failed or gzip_failed
        if compiled is None:
            if f.files_without_match:
                all_results.append(p.raw_path)
            continue
        # zgrep hands grep a stdin operand as `-`, so -l and -L list it
        # as `-` while its lines are labelled `(standard input)` (gzip
        # 1.13); /dev/stdin is named as typed either way.
        fname = operand_label(p, "(standard input)") if show_filename else None
        if f.files_only or f.files_without_match:
            matched = _files_only_match(data, compiled, f.invert)
            # -L lists the files that selected nothing; the status
            # still follows the matching, as GNU grep's does.
            if matched == f.files_only:
                all_results.append(p.raw_path)
            any_match = any_match or matched
        else:
            result, had_match = _zgrep_search(data, compiled, f.invert,
                                              f.count, f.line_numbers, fname,
                                              f.only_matching, f.max_count,
                                              f.byte_offsets)
            if had_match:
                any_match = True
            all_results.extend(result)

    # gzip's failure is exit 2 even beside a match, -q included (zgrep
    # 1.13 takes the more serious status of gzip's and grep's per file).
    exit_code = 2 if failed else 0 if any_match else 1
    stderr = "".join(errors).encode() or None
    # Under -m0, GNU still prints -L's operands even with -q.
    if (f.quiet and f.max_count != 0) or not all_results:
        return None, IOResult(exit_code=exit_code, stderr=stderr)
    return format_records(all_results), IOResult(exit_code=exit_code,
                                                 stderr=stderr)


__all__ = ["zgrep"]
