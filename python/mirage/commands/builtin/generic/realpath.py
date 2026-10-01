import posixpath
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

from mirage.commands.builtin.utils.paths import dispatch_stat, link_follow
from mirage.commands.builtin.utils.wrap import to_pathspec
from mirage.commands.config import CommandOpts
from mirage.commands.spec import SPECS
from mirage.commands.spec.flag_view import FlagView
from mirage.commands.spec.types import FlagValue
from mirage.commands.spec.usage import missing_operand_error
from mirage.io.types import ByteSource, IOResult
from mirage.runtime.types import DispatchFn
from mirage.types import FileStat, FileType, PathSpec, StatFn
from mirage.utils.errors import eloop, enoent, enotdir, fs_error_line
from mirage.utils.key_prefix import mount_prefix_of
from mirage.utils.path import CycleError

PathStat = Callable[[str], Awaitable[FileStat]]

_MODES = {"canonicalize_existing": "e", "canonicalize_missing": "m"}
_LINKS = {"logical": "L", "physical": "P", "strip": "s", "no_symlinks": "s"}


@dataclass(frozen=True, slots=True)
class RealpathFlags:
    """GNU realpath's options, the last of each family winning.

    Args:
        mode (str): ``e`` every component must exist, ``m`` none has to,
            empty for all but the last (the default).
        links (str): ``P`` resolves each link as the walk meets it, ``L``
            resolves the ``..`` components first, ``s`` resolves none.
        quiet (bool): ``-q``, no message for an operand that fails.
        zero (bool): ``-z``, each line ends in NUL.
        relative_to (str | None): ``--relative-to``.
        relative_base (str | None): ``--relative-base``.
    """
    mode: str = ""
    links: str = "P"
    quiet: bool = False
    zero: bool = False
    relative_to: str | None = None
    relative_base: str | None = None


def parse_flags(flags: Mapping[str, FlagValue]) -> RealpathFlags:
    fl = FlagView(flags, spec=SPECS["realpath"])
    modes = fl.typed_order(*_MODES)
    links = fl.typed_order(*_LINKS)
    return RealpathFlags(mode=_MODES[modes[-1]] if modes else "",
                         links=_LINKS[links[-1]] if links else "P",
                         quiet=fl.as_bool("quiet"),
                         zero=fl.as_bool("zero"),
                         relative_to=fl.as_str("relative_to"),
                         relative_base=fl.as_str("relative_base"))


async def _directory(stat: PathStat, path: str, word: str) -> None:
    if (await stat(path)).type != FileType.DIRECTORY:
        raise enotdir(word)


async def canonicalize(word: str, cwd: str, mode: str, nolinks: bool,
                       follow: Callable[[str], str] | None,
                       stat: PathStat) -> str:
    """gnulib's canonicalize_filename_mode, over the workspace, which
    ``realpath`` and ``readlink -f`` share.

    A relative word starts at the working directory. Each named component
    is appended and, unless ``nolinks``, taken through its links, so a
    ``..`` climbs from where a link leads. A component a ``.``, ``..`` or
    trailing slash follows must be a directory; then the whole path must
    be there, except that the default mode lets the last component alone
    be missing, and ``nolinks`` blames any missing one on the last. ``m``
    checks nothing and leaves a looping link unresolved.

    Args:
        word (str): the path as given.
        cwd (str): the working directory, physical as getcwd's.
        mode (str): ``e``, ``m`` or empty, as ``RealpathFlags.mode``.
        nolinks (bool): resolve no link (``-s``, and ``-L``'s first pass).
        follow (Callable[[str], str] | None): the namespace's link
            resolution, None while it holds no link.
        stat (PathStat): the workspace's stat of one path.

    Raises:
        OSError: the first check the walk fails.
    """
    if not word:
        raise enoent(word)
    names = [n for n in posixpath.join(cwd, word).split("/") if n]
    path = "/"
    for i, name in enumerate(names):
        if name in (".", ".."):
            path = posixpath.dirname(path) if name == ".." else path
            continue
        path = posixpath.join(path, name)
        try:
            path = path if nolinks or follow is None else follow(path)
        except CycleError as exc:
            if mode != "m":
                raise eloop(word) from exc
        if mode != "m" and names[i + 1:i + 2] in ([".."], ["."]):
            await _directory(stat, path, word)
    if mode == "m" or names[-1:] in ([], [".."], ["."]):
        return path
    try:
        if word.endswith("/"):
            await _directory(stat, path, word)
        else:
            await stat(path)
    except FileNotFoundError:
        if mode == "e":
            raise
        if not nolinks:
            await _directory(stat, posixpath.dirname(path), word)
    return path


def _under(base: str, path: str) -> bool:
    return base == "/" or path == base or path.startswith(base + "/")


def _relative(path: str, base: str) -> str:
    common = posixpath.commonpath([path, base])
    climb = base[len(common):].strip("/")
    rest = path[len(common):].strip("/")
    parts = [".."] * (climb.count("/") + 1 if climb else 0)
    return "/".join(parts + ([rest] if rest else [])) or "."


async def realpath(
    paths: list[PathSpec],
    *,
    stat: PathStat,
    cwd: str = "/",
    follow: Callable[[str], str] | None = None,
    flags: RealpathFlags = RealpathFlags(),
) -> tuple[ByteSource | None, IOResult]:
    """Print each operand's canonical path, GNU ``realpath`` (9.7).

    An operand that does not resolve is reported and the rest still
    print, exit 1. A ``--relative-to`` or ``--relative-base`` directory
    resolves the same way first, and one that does not ends the command.

    Args:
        paths (list[PathSpec]): the operands, read as typed.
        stat (PathStat): the workspace's stat of one path.
        cwd (str): the working directory.
        follow (Callable[[str], str] | None): the namespace's link
            resolution, None while it holds no link.
        flags (RealpathFlags): the parsed options.
    """
    if not paths:
        raise missing_operand_error("realpath", None)

    async def canon(word: str) -> str:
        path = await canonicalize(word, cwd, flags.mode, flags.links != "P",
                                  follow, stat)
        if flags.links != "L":
            return path
        return await canonicalize(path, cwd, flags.mode, False, follow, stat)

    async def directory(word: str) -> str:
        path = await canon(word)
        if flags.mode == "e":
            await _directory(stat, path, word)
        return path

    relative_to = flags.relative_to or flags.relative_base
    to = base = None
    for word in dict.fromkeys(w for w in (relative_to, flags.relative_base)
                              if w is not None):
        try:
            path = await directory(word)
        except OSError as exc:
            return None, IOResult(exit_code=1,
                                  stderr=fs_error_line("realpath", word,
                                                       exc).encode())
        if word != relative_to:
            to, base = (to, path) if _under(path, to or "/") else (None, to)
        else:
            to, base = path, path if word == flags.relative_base else None
    lines: list[str] = []
    errors: list[str] = []
    failed = False
    for p in paths:
        try:
            path = await canon(p.raw_path)
        except OSError as exc:
            failed = True
            if not flags.quiet:
                errors.append(fs_error_line("realpath", p, exc))
            continue
        if to is None or (base is not None and not _under(base, path)):
            lines.append(path)
        else:
            lines.append(_relative(path, to))
    end = "\0" if flags.zero else "\n"
    out = "".join(line + end for line in lines).encode() or None
    return out, IOResult(stderr="".join(errors).encode() or None,
                         exit_code=1 if failed else 0)


def door_stat(dispatch: DispatchFn) -> PathStat:
    """The workspace's stat of one path, through the op door.

    Args:
        dispatch (DispatchFn): op dispatcher.
    """
    return lambda path: dispatch_stat(dispatch, PathSpec.from_str_path(path))


async def realpath_generic(
    paths: list[PathSpec],
    texts: list[str],
    opts: CommandOpts,
    stat_fn: StatFn,
) -> tuple[ByteSource | None, IOResult]:
    prefix = (mount_prefix_of(paths[0].virtual, paths[0].vfs_path)
              if paths else "")

    async def stat(path: str) -> FileStat:
        return await stat_fn(to_pathspec(path, prefix))

    return await realpath(
        paths,
        stat=door_stat(opts.dispatch) if opts.dispatch is not None else stat,
        cwd=opts.cwd.virtual,
        follow=link_follow(opts.ns.links if opts.ns is not None else None),
        flags=parse_flags(opts.flags))
