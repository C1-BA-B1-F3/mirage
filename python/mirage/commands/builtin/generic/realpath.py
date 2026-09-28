import posixpath
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import partial

from mirage.commands.builtin.utils.paths import (absent_dest_strerror,
                                                 dot_refusal, link_follow,
                                                 stat_or_enoent)
from mirage.commands.builtin.utils.wrap import to_pathspec
from mirage.commands.config import CommandOpts
from mirage.commands.spec import SPECS
from mirage.commands.spec.flag_view import FlagView
from mirage.commands.spec.types import FlagValue
from mirage.io.types import ByteSource, IOResult
from mirage.types import PathSpec, StatFn
from mirage.utils.errors import enoent, enotdir, fs_error_line
from mirage.utils.key_prefix import mount_prefix_of


async def _exists(stat_fn: StatFn, path: PathSpec) -> bool:
    try:
        await stat_fn(path)
        return True
    except (FileNotFoundError, ValueError):
        return False


async def _unresolved(p: PathSpec, resolved: PathSpec, *, stat_fn: StatFn,
                      walk: StatFn | None, follow: Callable[[str], str] | None,
                      e: bool, m: bool) -> OSError | None:
    """Why one operand does not resolve under the requested mode.

    GNU's three modes ask for different amounts of the path: ``-m`` for
    nothing, the default for every component but the last, ``-e`` for
    all of it. A ``.`` or ``..`` resolves against the directory in front
    of it, so outside ``-m`` the dots walk first.

    Args:
        p (PathSpec): the operand as typed.
        resolved (PathSpec): the operand normalized, on its mount.
        stat_fn (StatFn): backend stat.
        walk (StatFn | None): workspace stat, None outside a workspace.
        follow (Callable[[str], str] | None): the namespace's link
            resolution, which the operand may already have been taken
            through.
        e (bool): ``-e``, every component must exist.
        m (bool): ``-m``, no component has to.
    """
    if m:
        return None
    if walk is not None:
        refusal = await dot_refusal(walk, p, follow)
        if refusal is not None:
            return refusal
    if e:
        return None if await _exists(stat_fn, resolved) else enoent(p)
    if walk is None:
        return None
    why = await absent_dest_strerror(walk, resolved)
    if why is None:
        return None
    return enotdir(p) if why == "Not a directory" else enoent(p)


async def realpath(
    paths: list[PathSpec],
    *,
    stat_fn: StatFn,
    walk: StatFn | None = None,
    follow: Callable[[str], str] | None = None,
    e: bool = False,
    m: bool = False,
) -> tuple[ByteSource | None, IOResult]:
    """Print each operand's canonical path, GNU ``realpath``.

    An operand that does not resolve is reported and the rest still
    print, exit 1 (coreutils 9.7).

    Args:
        paths (list[PathSpec]): the operands.
        stat_fn (StatFn): backend stat.
        walk (StatFn | None): workspace stat, None outside a workspace.
        follow (Callable[[str], str] | None): the namespace's link
            resolution.
        e (bool): ``-e``.
        m (bool): ``-m``.
    """
    lines: list[str] = []
    errors: list[str] = []
    for p in paths:
        resolved_display = posixpath.normpath(p.virtual)
        resolved = to_pathspec(resolved_display,
                               mount_prefix_of(p.virtual, p.vfs_path))
        failure = await _unresolved(p,
                                    resolved,
                                    stat_fn=stat_fn,
                                    walk=walk,
                                    follow=follow,
                                    e=e,
                                    m=m)
        if failure is not None:
            errors.append(fs_error_line("realpath", p, failure))
            continue
        lines.append(resolved_display)
    out = ("\n".join(lines) + "\n").encode() if lines else None
    stderr = "".join(errors).encode() if errors else None
    return out, IOResult(stderr=stderr, exit_code=1 if errors else 0)


__all__ = ["realpath"]


@dataclass(frozen=True, slots=True)
class RealpathFlags:
    must_exist: bool = False
    allow_missing: bool = False


def parse_flags(flags: Mapping[str, FlagValue]) -> RealpathFlags:
    fl = FlagView(flags, spec=SPECS["realpath"])
    return RealpathFlags(must_exist=fl.as_bool("e"),
                         allow_missing=fl.as_bool("m"))


async def realpath_generic(
    paths: list[PathSpec],
    texts: list[str],
    opts: CommandOpts,
    stat_fn: StatFn,
) -> tuple[ByteSource | None, IOResult]:
    parsed = parse_flags(opts.flags)
    walk = (partial(stat_or_enoent, opts.stat_path)
            if opts.stat_path is not None else None)
    return await realpath(
        paths,
        stat_fn=stat_fn,
        walk=walk,
        follow=link_follow(opts.ns.links if opts.ns is not None else None),
        e=parsed.must_exist,
        m=parsed.allow_missing)
