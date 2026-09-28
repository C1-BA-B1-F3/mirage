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

import dataclasses
import posixpath
from functools import partial

from mirage.commands.builtin.generic.cp import dest_kind
from mirage.commands.builtin.utils.paths import dispatch_stat
from mirage.commands.spec import SPECS, parse_command, parse_to_kwargs
from mirage.commands.spec.flag_view import FlagView
from mirage.commands.spec.types import FlagValue
from mirage.runtime.types import DispatchFn
from mirage.types import FileStat, FileType, PathSpec
from mirage.utils.errors import (ELOOP_STRERROR, FS_ERRORS, DotWalkLoop,
                                 fs_strerror)
from mirage.utils.path import CycleError
from mirage.workspace.executor.builtins.links.probe import stat_or_none
from mirage.workspace.executor.builtins.shared import fail, ok, split_flags
from mirage.workspace.executor.builtins.types import MvMove, Result
from mirage.workspace.mount.namespace import Namespace


def link_flags(args: list[str | PathSpec], known: str) -> set[str]:
    flags, _ = split_flags(args, known)
    return flags


def follow_parent(namespace: Namespace, virtual: str) -> str:
    """Resolve every component of a path but the last one.

    POSIX resolves a path one component at a time, and only the last one
    is exempt for an lstat-style command: ``stat dlink/f2`` reports
    ``f2`` because ``dlink`` was resolved on the way to it, while
    ``stat dlink`` reports the link. A no-follow command therefore still
    needs its operand's directory prefix resolved. The walk is the
    namespace's (``Namespace.follow_parent``, which the op door runs for
    every surface); the operand comes back without a trailing slash,
    which the slash-keeping commands read off ``raw_path`` instead.

    Args:
        namespace (Namespace): addressing authority holding the links.
        virtual (str): absolute virtual path.

    Raises:
        CycleError: when a prefix loops past the hop limit (ELOOP).
    """
    trimmed = virtual.rstrip("/")
    return namespace.follow_parent(trimmed) if trimmed else virtual


def follow_paths(
    namespace: Namespace,
    items: list[str | PathSpec],
    follow_last: bool = True,
    slash_follows: bool = True,
) -> list[str | PathSpec]:
    """Rewrite path operands through the symlink table (open(2) semantics).

    The directory prefix always resolves; ``follow_last`` decides the
    final component, which is the whole difference between open(2) and
    lstat(2). A trailing slash overrides it per operand, because POSIX
    reads ``dlink/`` as ``dlink/.`` and there is no ``.`` to reach
    without resolving the link first (GNU: ``stat dlink`` is a symbolic
    link, ``stat dlink/`` is a directory).

    Non-path items and paths that resolve to themselves pass through
    untouched. A rewritten spec keeps the user-typed form in ``raw_path``
    so error messages still name the operand as typed; the mount re-stamps
    ``vfs_path`` at dispatch. A path a link loop stands in resolves to
    nothing, so it stays as typed with ``walk_error`` set, and the op that
    reaches it answers ELOOP: GNU reports the one operand in the command's
    own words and goes on to the next.

    Args:
        namespace (Namespace): addressing authority holding the link table.
        items (list[str | PathSpec]): classified command parts.
        follow_last (bool): whether the command resolves the final
            component of its own accord (open(2) rather than lstat(2)).
        slash_follows (bool): whether a trailing slash may override
            ``follow_last``; False only for ``tar``, which strips the
            slash before it stats.
    """
    out: list[str | PathSpec] = []
    for item in items:
        if not isinstance(item, PathSpec):
            out.append(item)
            continue
        last = follow_last or (slash_follows and item.raw_path.endswith("/"))
        try:
            followed = (namespace.follow(item.virtual)
                        if last else follow_parent(namespace, item.virtual))
        except CycleError:
            out.append(dataclasses.replace(item, walk_error="ELOOP"))
            continue
        # A relative target climbs from the link's own directory, which
        # is a real one, so its `..` collapses the way resolve_link
        # collapses it; left in, the path no longer matched the word that
        # spelled it and the operand lost its typed name (`wc -c sub/al`
        # printed `/data/sub/../a`).
        virtual = posixpath.normpath(followed)
        if followed.endswith("/") and virtual != "/":
            virtual += "/"
        if virtual == item.virtual:
            out.append(item)
            continue
        out.append(
            dataclasses.replace(item,
                                virtual=virtual,
                                directory=virtual[:virtual.rfind("/") + 1]
                                or "/",
                                vfs_path=""))
    return out


async def follow_directory_links(
        namespace: Namespace, dispatch: DispatchFn,
        items: list[str | PathSpec]) -> list[str | PathSpec]:
    """Resolve each command-line link that leads to a directory.

    GNU ls's default (ls.c's DEREF_COMMAND_LINE_SYMLINK_TO_DIR, coreutils
    9.7): ``ls dlink`` lists the directory, while ``ls flink`` and a
    dangling ``ls dang`` report the link itself, and so does a loop, whose
    stat fails where GNU then lstats it. Where a link leads takes a stat
    through the door to know, since the target may live on any mount, so
    this runs after ``follow_paths`` has resolved every operand's prefix.

    Args:
        namespace (Namespace): addressing authority holding the links.
        dispatch (DispatchFn): op dispatcher used to stat each target.
        items (list[str | PathSpec]): classified command parts, their
            last components not yet resolved.
    """
    out: list[str | PathSpec] = []
    for item in items:
        if (not isinstance(item, PathSpec) or item.walk_error is not None
                or not namespace.is_link(item.virtual)):
            out.append(item)
            continue
        followed = follow_paths(namespace, [item])[0]
        leads_to_dir = False
        if isinstance(followed, PathSpec) and followed.walk_error is None:
            try:
                target = await stat_or_none(dispatch, followed)
            except DotWalkLoop:
                target = None
            leads_to_dir = (target is not None
                            and target.type == FileType.DIRECTORY)
        out.append(followed if leads_to_dir else item)
    return out


def accepts_line(name: str, args: tuple[str, ...], items: list[str | PathSpec],
                 cwd: str) -> bool:
    """Whether the command layer will act on this line as written.

    A link entry lives in the namespace, so ``strip_link_operands``
    removes it before the command runs, and the command layer can
    neither see that nor undo it. GNU validates the whole line first and
    removes nothing when it refuses: ``rm --bogus dlink`` reports the
    option and ``unlink dlink other`` reports the extra operand, both
    with every link still in place. So the strip runs only for a line
    that layer accepts, and a refused one falls through to it unchanged
    to be reported there. Option errors are the parser's, which reports
    rather than raises them; unlink's one-operand grammar is its
    builder's, and reporting it needs the operands to arrive intact.

    Args:
        name (str): command name.
        args (tuple[str, ...]): the line's words after the name.
        items (list[str | PathSpec]): classified command parts.
        cwd (str): session working directory, which the parser resolves
            path operands against.
    """
    spec = SPECS.get(name)
    if spec is None:
        return True
    parsed = parse_command(spec, list(args), cwd, name)
    if parsed.invalid_options or parsed.ambiguous_options:
        return False
    if name == "unlink":
        return sum(1 for i in items if isinstance(i, PathSpec)) <= 1
    return True


async def strip_link_operands(
    name: str,
    dispatch: DispatchFn,
    namespace: Namespace,
    items: list[str | PathSpec],
    args: tuple[str, ...],
    cwd: str,
) -> tuple[list[str | PathSpec], int, list[str]]:
    """Unlink and drop ``rm``/``unlink`` operands that are symlinks.

    GNU ``rm`` removes the link itself and never follows it; a dangling
    link removes fine. Remaining operands stay for backend dispatch.

    The removal is a dispatch op, never a direct table write: the door
    is where session grants, the turf's mode, admission policies and
    the op ledger fire, and writing the table from here let a session
    delete a link its grant reads and a policy protecting one never
    fired (the same hole the FUSE unlink had). A refused operand does
    not stop the rest, which is also rm's rule for a backend operand;
    ``-f`` silences only the absent (a hidden link answers ENOENT, the
    no-name-leak rule).

    The refusal is voiced the way the same refusal on a backend file is
    voiced, so one grant does not describe itself two ways: GNU's
    per-operand line, a read-only region's EROFS included.

    An operand typed with a trailing slash is deliberately kept: the
    slash asked for a directory, and GNU refuses rather than removing
    the link (``rm dlink/`` is "Is a directory", ``unlink dlink/`` is
    "Not a directory"). Removing it here would delete exactly what the
    slash was protecting, so the command reports it instead.

    Args:
        name (str): the command, ``rm`` or ``unlink`` (picks the
            refusal verb, and only rm has ``-f``).
        dispatch (DispatchFn): op dispatcher (the door).
        namespace (Namespace): addressing authority holding the link table.
        items (list[str | PathSpec]): classified command parts.
        args (tuple[str, ...]): the line's words after the name, parsed
            for rm's ``-f``.
        cwd (str): session working directory the parse resolves against.

    Returns:
        tuple[list[str | PathSpec], int, list[str]]: surviving parts,
        the number of link operands consumed (removed, refused or
        force-silenced), and the refusal lines.
    """
    force = False
    if name == "rm":
        force = bool(
            parse_command(SPECS["rm"], list(args), cwd, "rm").flags.get("-f"))
    verb = "remove" if name == "rm" else "unlink"
    handled = 0
    errors: list[str] = []
    kept: list[str | PathSpec] = []
    for item in items:
        if (isinstance(item, PathSpec) and not item.raw_path.endswith("/")
                and namespace.is_link(item.virtual)):
            handled += 1
            try:
                await dispatch("unlink", item)
            except FileNotFoundError as exc:
                if not force:
                    errors.append(f"{name}: cannot {verb} '{item.raw_path}': "
                                  f"{fs_strerror(exc)}\n")
            except FS_ERRORS as exc:
                errors.append(f"{name}: cannot {verb} '{item.raw_path}': "
                              f"{fs_strerror(exc)}\n")
            continue
        kept.append(item)
    return kept, handled, errors


async def _slashed_link_refusal(
    namespace: Namespace,
    dispatch: DispatchFn,
    src: PathSpec,
    dst: PathSpec,
    dst_stat: FileStat | None,
) -> Result:
    """GNU's refusal for an ``mv`` source that is a link typed with a slash.

    rename(2) never follows, so the slash is not resolved away: POSIX
    reads ``dlink/`` as ``dlink/.``, which asks for a directory the call
    will not resolve, and GNU refuses with everything left in place --
    where a bare ``dlink`` renames the link entry. Which of the four
    wordings applies follows mv's own order, source stat before
    destination type before the rename itself, and all four are pinned
    against GNU coreutils 9.7.

    Args:
        namespace (Namespace): addressing authority holding the link table.
        dispatch (DispatchFn): op dispatcher used to stat the target.
        src (PathSpec): the slashed link source.
        dst (PathSpec): destination as typed.
        dst_stat (FileStat | None): the destination's stat, None when it
            does not exist.
    """
    try:
        followed = namespace.follow(src.virtual)
    except CycleError:
        return fail(
            "mv", f"mv: cannot stat '{src.raw_path}': "
            f"{ELOOP_STRERROR}\n")
    target = await stat_or_none(dispatch, PathSpec.from_str_path(followed))
    if target is None:
        return fail(
            "mv", f"mv: cannot stat '{src.raw_path}': "
            "No such file or directory\n")
    if target.type != FileType.DIRECTORY:
        return fail("mv",
                    f"mv: cannot stat '{src.raw_path}': Not a directory\n")
    if dst_stat is not None and dst_stat.type != FileType.DIRECTORY:
        return fail(
            "mv", f"mv: cannot overwrite non-directory '{dst.raw_path}' "
            f"with directory '{src.raw_path}'\n")
    landing = dst.raw_path
    if dst_stat is not None:
        landing = landing.rstrip("/") + "/" + posixpath.basename(src.virtual)
    return fail(
        "mv", f"mv: cannot move '{src.raw_path}' to '{landing}': "
        "Not a directory\n")


async def prepare_mv(
    namespace: Namespace,
    dispatch: DispatchFn,
    items: list[str | PathSpec],
    args: tuple[str, ...],
    cwd: str,
) -> tuple[list[str | PathSpec], list[MvMove], Result | None, list[str]]:
    """Adjust an ``mv`` line for node-meta operands.

    A link source renames the link entry itself. A destination that is
    (a link to) a directory receives the move inside it (rename(2)
    preceded by mv's dst stat); any other destination is replaced, so its
    node entry, link or overlay attrs alike, drops once the backend move
    succeeds. A plain source hands back the pair to re-anchor once the
    backend move succeeds, so whatever the node table holds at it and
    below it travels with the bytes.

    This has to be done here: a single-mount ``mv`` renames through the
    backend op bound to the accessor rather than through the dispatcher,
    so the re-anchoring the dispatcher does for every other caller has to
    be repeated. ``-t`` and ``-T`` are read off the parsed line rather
    than guessed from the parts, since a path-shaped flag value is
    classified into a PathSpec exactly as an operand is.

    Args:
        namespace (Namespace): addressing authority holding the node table.
        dispatch (DispatchFn): op dispatcher used to stat the destination.
        items (list[str | PathSpec]): classified command parts.
        args (tuple[str, ...]): the line's words after the name, read
            for the two options that move the destination.
        cwd (str): session working directory, which the parser resolves
            path operands against.

    Returns:
        tuple: (possibly rewritten parts, the (source, landing) pairs
        whose node entries follow the bytes once each move is confirmed,
        early result when the line completed as namespace renames, error
        lines for link sources the rename refused).
    """
    paths = [p for p in items if isinstance(p, PathSpec)]
    fl = FlagView(parse_to_kwargs(
        parse_command(SPECS["mv"], list(args), cwd, "mv")),
                  spec=SPECS["mv"])
    target = fl.raw("target_directory")
    if target is not None or len(paths) > 2:
        return await _prepare_many(namespace, dispatch, items, paths, target)
    if len(paths) != 2:
        return items, [], None, []
    rewritten, moves, early = await _prepare_pair(namespace, dispatch, items,
                                                  paths, fl)
    return rewritten, moves, early, []


async def settle_moves(namespace: Namespace, dispatch: DispatchFn,
                       moves: list[MvMove], exit_code: int) -> None:
    """Carry the node table across the moves the backend completed.

    A move is confirmed by its landing, because a several-source mv can
    fail one source and move the rest: a landing that appeared is a move
    that happened. A landing that was already there (a link included,
    which shadows whatever lands under its name) is replaced by the move,
    which only the line's status can confirm. The source cannot confirm
    anything, since a link left below a moved directory synthesizes that
    directory back. The landing is replaced the way rename(2) replaces it,
    node and subtree alike, and then the source's own node and subtree
    land on it, the same four steps the dispatcher takes for a rename it
    forwards itself.

    Args:
        namespace (Namespace): addressing authority holding the node table.
        dispatch (DispatchFn): op dispatcher used to confirm each move.
        moves (list[MvMove]): the pairs ``prepare_mv`` handed back.
        exit_code (int): the backend mv's status.
    """
    for src, landing, replaced in moves:
        if replaced:
            if exit_code != 0:
                continue
        elif not await _present(dispatch, landing):
            continue
        await namespace.unlink(landing)
        await namespace.purge_under(landing)
        await namespace.rename(src, landing)
        await namespace.rename_under(src, landing)


async def _present(dispatch: DispatchFn, virtual: str) -> bool:
    """Whether a path resolves to an entry; a link loop resolves to none.

    Args:
        dispatch (DispatchFn): op dispatcher used to stat the path.
        virtual (str): absolute virtual path.
    """
    try:
        return await stat_or_none(dispatch,
                                  PathSpec.from_str_path(virtual)) is not None
    except DotWalkLoop:
        return False


async def _moves(namespace: Namespace, dispatch: DispatchFn,
                 pairs: list[tuple[PathSpec, str]]) -> list[MvMove]:
    """Each (source, landing) pair, with whether the landing is already
    there, which ``settle_moves`` reads to confirm the move.

    Args:
        namespace (Namespace): addressing authority holding the node table.
        dispatch (DispatchFn): op dispatcher used to stat each landing.
        pairs (list[tuple[PathSpec, str]]): each source with its landing.
    """
    moves: list[MvMove] = []
    for src, landing in pairs:
        there = namespace.is_link(landing) or await _present(dispatch, landing)
        moves.append((src.virtual, landing, there))
    return moves


def _landing_key(path: str) -> str:
    return path.rstrip("/") or "/"


async def _prepare_many(
    namespace: Namespace,
    dispatch: DispatchFn,
    items: list[str | PathSpec],
    paths: list[PathSpec],
    target: FlagValue | None,
) -> tuple[list[str | PathSpec], list[MvMove], Result | None, list[str]]:
    """An ``mv`` of sources into one destination directory.

    ``mv a b dst`` and ``mv -t dst a ...``. GNU stats the destination
    through its link before anything moves: a link to a directory takes
    the sources, a link to anything else is not a directory, a dangling
    one is missing and a loop is ELOOP, each worded by the generic mv from
    the destination handed to it here (coreutils 9.7). Every source then
    lands at the directory plus its basename: a link source through the
    namespace, which no backend mv can see, and every other one with its
    node entries re-anchored once the backend confirms the move.

    Args:
        namespace (Namespace): addressing authority holding the node table.
        dispatch (DispatchFn): op dispatcher for the stats and renames.
        items (list[str | PathSpec]): classified command parts.
        paths (list[PathSpec]): the PathSpecs among them, in line order.
        target (FlagValue | None): ``-t``'s resolved value, if given.
    """
    if target is not None:
        spelled = target.virtual if isinstance(target,
                                               PathSpec) else str(target)
        dst = next((p for p in paths
                    if _landing_key(p.virtual) == _landing_key(spelled)), None)
        if dst is None:
            return items, [], None, []
        sources = [p for p in paths if p is not dst]
    else:
        dst, sources = paths[-1], paths[:-1]
    if dst.walk_error is not None:
        return items, [], None, []
    followed = follow_paths(namespace, [dst])[0]
    assert isinstance(followed, PathSpec)
    rewritten = [followed if item is dst else item for item in items]
    if followed.walk_error is not None:
        return rewritten, [], None, []
    stat = await stat_or_none(dispatch,
                              PathSpec.from_str_path(followed.virtual))
    if stat is None or stat.type != FileType.DIRECTORY:
        return rewritten, [], None, []
    base = followed.virtual.rstrip("/")
    typed = dst.raw_path.rstrip("/")
    pairs: list[tuple[PathSpec, str]] = []
    errors: list[str] = []
    for src in sources:
        if src.walk_error is not None:
            continue
        name = posixpath.basename(src.virtual.rstrip("/"))
        landing = f"{base}/{name}"
        if not namespace.is_link(src.virtual) or src.raw_path.endswith("/"):
            pairs.append((src, landing))
            continue
        # A link has no backend entry for the generic mv to move, so the
        # door renames it, where every other mv's admission gates apply.
        rewritten = [item for item in rewritten if item is not src]
        try:
            await dispatch("rename", src, dst=PathSpec.from_str_path(landing))
        except FS_ERRORS as exc:
            shown = f"{typed}/{posixpath.basename(src.raw_path.rstrip('/'))}"
            errors.append(f"mv: cannot move '{src.raw_path}' to '{shown}': "
                          f"{fs_strerror(exc)}\n")
    if not any(
            isinstance(item, PathSpec) and item is not followed
            for item in rewritten):
        # Every source was a link, so the namespace finished the line.
        return rewritten, [], (fail("mv", "".join(errors))
                               if errors else ok("mv")), []
    return rewritten, await _moves(namespace, dispatch, pairs), None, errors


async def _prepare_pair(
    namespace: Namespace,
    dispatch: DispatchFn,
    items: list[str | PathSpec],
    paths: list[PathSpec],
    fl: FlagView,
) -> tuple[list[str | PathSpec], list[MvMove], Result | None]:
    """A two-operand ``mv``: one source and the destination it replaces
    or lands inside.

    Args:
        namespace (Namespace): addressing authority holding the node table.
        dispatch (DispatchFn): op dispatcher used to stat the destination.
        items (list[str | PathSpec]): classified command parts.
        paths (list[PathSpec]): the two PathSpecs, source first.
        fl (FlagView): the parsed line, read for ``-T``.
    """
    src, dst = paths
    if src.walk_error is not None or dst.walk_error is not None:
        # The walk refused the operand, so there is no entry to move or
        # land on; the generic mv reports it through its own stat, which
        # cannot see a link source. A link is a non-directory, and GNU
        # stats an empty destination as a directory (see mv_generic).
        if (dst.raw_path == "" and src.walk_error is None
                and namespace.is_link(src.virtual)):
            return items, [], fail(
                "mv", "mv: cannot overwrite directory '' with "
                f"non-directory '{src.raw_path}'\n")
        if (dst.walk_error == "ELOOP" and src.walk_error is None
                and namespace.is_link(src.virtual)):
            return items, [], fail(
                "mv", f"mv: cannot stat '{dst.raw_path}': {ELOOP_STRERROR}\n")
        return items, [], None

    # Where the move lands: inside a directory destination (followed, so
    # node-meta keys line up with the followed paths stat merges on), else
    # the destination itself, replaced like rename(2). A destination a
    # link loop stands in stats ELOOP, which mv reads as not a directory:
    # the rename replaces the link itself (GNU 9.7).
    try:
        followed: str | None = namespace.follow(dst.virtual)
    except CycleError:
        followed = None
    stat = (None if followed is None else await stat_or_none(
        dispatch, PathSpec.from_str_path(followed)))
    into_dir = (not fl.as_bool("no_target_directory") and stat is not None
                and stat.type == FileType.DIRECTORY)
    if into_dir and followed is not None:
        target_dst = (followed.rstrip("/") + "/" +
                      posixpath.basename(src.virtual))
    else:
        target_dst = dst.virtual

    if namespace.is_link(src.virtual):
        if src.raw_path.endswith("/"):
            return items, [], await _slashed_link_refusal(
                namespace, dispatch, src, dst, stat)
        if not into_dir and dst.raw_path.endswith("/"):
            # rename(2) never follows the source, so a link is not a
            # directory whatever it points at, and a slashed destination
            # asks for one: GNU 9.7 refuses `mv dlnk missing/` at the
            # rename and `mv dlnk reg/` at the destination's stat, the
            # same two wordings a regular source gets from the generic,
            # whose chain walk also keeps an absent parent's ENOENT
            # (`mv dlnk nodir/name/`) ahead of the slash.
            _, _, verdict = await dest_kind(partial(dispatch_stat, dispatch),
                                            dst)
            if verdict == "Not a directory":
                return items, [], fail(
                    "mv", f"mv: cannot stat '{dst.raw_path}': "
                    "Not a directory\n")
            return items, [], fail(
                "mv", f"mv: cannot move '{src.raw_path}' to "
                f"'{dst.raw_path}': {verdict or 'Not a directory'}\n")
        # The move is a node-table rename, which the door answers: a
        # link has no backend entry for the generic mv to move. Reaching
        # the table directly from here would skip the admission gates
        # every other mv passes, so the dispatch is the point.
        try:
            await dispatch("rename",
                           src,
                           dst=PathSpec.from_str_path(target_dst))
        except PermissionError as exc:
            # A read-only endpoint or a policy deny, which GNU voices
            # per operand and which the backend mv path voices the same
            # way.
            return items, [], fail(
                "mv", f"mv: cannot move '{src.raw_path}' to "
                f"'{dst.raw_path}': {fs_strerror(exc)}\n")
        except FileNotFoundError as exc:
            # The landing's parent is absent, which GNU meets at the
            # rename, as the generic mv words it for a regular file.
            return items, [], fail(
                "mv", f"mv: cannot move '{src.raw_path}' to "
                f"'{dst.raw_path}': {fs_strerror(exc)}\n")
        except NotADirectoryError as exc:
            # A plain file in the landing's chain, which GNU meets at the
            # destination's stat, before any rename.
            return items, [], fail(
                "mv", f"mv: cannot stat '{dst.raw_path}': "
                f"{fs_strerror(exc)}\n")
        return items, [], ok("mv")

    # Unconditional on what the table holds: a directory source carries a
    # whole subtree of node entries that no exact-path lookup at the
    # source can see, and a symlink below it is destroyed rather than
    # merely forgotten when they are left behind.
    moves = await _moves(namespace, dispatch, [(src, target_dst)])

    rewritten = items
    if into_dir and namespace.is_link(dst.virtual):
        rewritten = follow_paths(namespace, items)
    return rewritten, moves, None
