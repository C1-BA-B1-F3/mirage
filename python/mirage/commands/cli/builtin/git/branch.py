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

import asyncio
import fnmatch
from io import BytesIO

from dulwich.config import ConfigFile
from dulwich.objects import ObjectID
from dulwich.refs import Ref
from dulwich.repo import BaseRepo
from dulwich.walk import Walker

from mirage.commands.cli.builtin.git.constants import DWIM_RULES, HEAD
from mirage.commands.cli.builtin.git.errors import (  # yapf: disable
    BranchExistsError, BranchNameRequiredError, BranchUsageError,
    CheckedOutBranchError, GitError, InvalidBranchNameError, NoBranchError,
    NoWorkspaceError, RefLockError, UnknownSwitchError, UnmergedBranchError)
from mirage.commands.cli.builtin.git.format import short, subject
from mirage.commands.cli.builtin.git.inspect import repo_config
from mirage.commands.cli.builtin.git.io import read_optional, write_file
from mirage.commands.cli.builtin.git.objects import abbrev_for
from mirage.commands.cli.builtin.git.ref_filter import (RefFilter,
                                                        filter_words,
                                                        kept_refs, ref_filter,
                                                        without_filter_values)
from mirage.commands.cli.builtin.git.refs import (blocking_ref, delete_ref,
                                                  read_head, valid_ref_name,
                                                  write_ref)
from mirage.commands.cli.builtin.git.revparse import resolve_commit
from mirage.commands.cli.builtin.git.session import opened
from mirage.commands.cli.builtin.git.types import (HeadRef, RepoLocation,
                                                   Upstream)
from mirage.commands.cli.builtin.git.util import (  # yapf: disable
    check_operands, escaped, fatal, switches)
from mirage.commands.cli.types import CLIDoors, CLIInvocation
from mirage.commands.spec.flag_view import FlagView
from mirage.io.stream import yield_bytes
from mirage.io.types import ByteSource, IOResult
from mirage.runtime.types import DispatchFn

HEADS_PREFIX = b"refs/heads/"
REMOTES_PREFIX = b"refs/remotes/"
SYMREF_PREFIX = b"ref: "
CURRENT = "* "
OTHER = "  "
REMOTE = "remotes/"


def _symref_suffix(repo: BaseRepo, ref: bytes) -> str:
    """The ``-> target`` a symbolic ref carries in a branch listing.

    ``refs/remotes/origin/HEAD`` is a pointer, not a branch, and git
    renders it as ``remotes/origin/HEAD -> origin/main``. Empty for an
    ordinary ref.

    Args:
        repo (BaseRepo): repository holding the ref table.
        ref (bytes): full ref name.
    """
    raw = repo.refs.read_loose_ref(Ref(ref))
    if raw is None or not raw.startswith(SYMREF_PREFIX):
        return ""
    target = raw[len(SYMREF_PREFIX):].strip()
    if target.startswith(REMOTES_PREFIX):
        target = target[len(REMOTES_PREFIX):]
    return f" -> {target.decode()}"


async def _create(dispatch: DispatchFn, repo: BaseRepo, location: RepoLocation,
                  name: str, start: str | None) -> str:
    """Point a new branch at a commit, refusing to move an existing one.

    Returns what git prints about the upstream it set up, if any.

    Args:
        dispatch (DispatchFn): workspace op dispatcher.
        repo (BaseRepo): the opened repository.
        location (RepoLocation): the discovered repository.
        name (str): the branch name.
        start (str | None): the revision to start it at, HEAD when None.
    """
    # Before the start point resolves, which is git's order here and
    # the opposite of switch's. A ref is a path below .git, so an
    # unchecked name reaches write_ref as one.
    if not valid_ref_name(name):
        raise InvalidBranchNameError(name)
    ref = f"{HEADS_PREFIX.decode()}{name}"
    if Ref(ref.encode()) in repo.refs.allkeys():
        raise BranchExistsError(name)
    commit = resolve_commit(repo, start or HEAD)
    # Last, as it is for git: a ref whose path another ref already
    # holds fails when the lock is taken, so a bad start point is
    # reported first.
    held = blocking_ref(repo.refs.allkeys(), ref)
    if held is not None:
        raise RefLockError(ref, held)
    await write_ref(dispatch, location.commondir, ref, commit.id)
    return await set_up_tracking(dispatch, repo, location, name, start)


def remote_branch(repo: BaseRepo, name: str) -> str | None:
    """The one remote-tracking branch a missing branch name guesses at.

    ``checkout <name>`` and ``switch <name>`` with no such branch create
    it from ``<remote>/<name>`` when exactly one remote has one.

    Args:
        repo (BaseRepo): the opened repository.
        name (str): the branch name asked for.
    """
    found = [
        ref.decode() for ref in repo.refs.allkeys()
        if ref.startswith(REMOTES_PREFIX) and ref.endswith(f"/{name}".encode())
        and ref.count(b"/") == 3 + name.count("/")
    ]
    return found[0] if len(found) == 1 else None


async def set_up_tracking(dispatch: DispatchFn, repo: BaseRepo,
                          location: RepoLocation, branch: str,
                          start: str | None) -> str:
    """Record a new branch's upstream when it starts at a remote's branch.

    git's ``branch.autoSetupMerge`` default: a start point naming
    ``<remote>/<branch>`` of a configured remote writes
    ``branch.<new>.remote`` and ``.merge`` and says so on stdout (pinned
    against git 2.47.3 and 2.50.1).

    Args:
        dispatch (DispatchFn): workspace op dispatcher.
        repo (BaseRepo): the opened repository.
        location (RepoLocation): the discovered repository.
        branch (str): the branch just created.
        start (str | None): the start point as typed.
    """
    if start is None:
        return ""
    known = repo.refs.allkeys()
    ref = next(
        (rule.format(start)
         for rule in DWIM_RULES if Ref(rule.format(start).encode()) in known),
        None)
    if ref is None or not ref.startswith(REMOTES_PREFIX.decode()):
        return ""
    remote, _, name = ref[len(REMOTES_PREFIX):].partition("/")
    path = f"{location.commondir}/config"
    data = await read_optional(dispatch, path) or b""
    cfg = ConfigFile.from_file(BytesIO(data))
    if not name or name == HEAD or not cfg.has_section(
        (b"remote", remote.encode())):
        return ""
    section = (f'[branch "{branch}"]\n\tremote = {remote}\n'
               f"\tmerge = refs/heads/{name}\n")
    await write_file(dispatch, path, data + section.encode())
    return f"branch '{branch}' set up to track '{remote}/{name}'.\n"


def head_commit(repo: BaseRepo, head: HeadRef) -> bytes | None:
    """The commit HEAD resolves to, None on an unborn branch.

    HEAD carries an object id only when detached; attached it names a
    ref, which is unset until the first commit.

    Args:
        repo (BaseRepo): the opened repository.
        head (HeadRef): what HEAD points at.
    """
    if head.commit is not None:
        return head.commit.encode()
    if head.ref is None:
        return None
    ref = Ref(head.ref.encode())
    return repo.refs[ref] if ref in repo.refs.allkeys() else None


def _merged(repo: BaseRepo, sha: bytes, head: bytes | None) -> bool:
    """Whether HEAD already holds every commit a branch points at.

    Synchronous, and called on a worker thread: walking ancestry pulls
    commit objects through the dispatcher. The walk stops at the first
    sighting, so a merged branch costs only as much history as separates
    it from HEAD; only a negative answer walks the whole thing, which is
    what any repository without a commit graph pays.

    An unborn HEAD holds nothing, which is git's answer too: on an
    orphan branch every other branch reads as unmerged.

    ``dulwich.graph.can_fast_forward`` answers exactly this question and
    cannot be used: it asks the repository for its grafts and shallow
    boundary, and a bare ``BaseRepo`` raises rather than answering.
    ``Walker`` is what ``log`` already walks with, and it needs only the
    object store.

    Only HEAD is consulted. git also accepts a branch contained in its
    own upstream, and there are no remotes here to have one.

    Args:
        repo (BaseRepo): the opened repository.
        sha (bytes): the branch tip.
        head (bytes | None): the commit HEAD resolves to.
    """
    if head is None:
        return False
    if sha == head:
        return True
    return any(entry.commit.id == sha
               for entry in Walker(repo.object_store, [ObjectID(head)]))


async def _delete(dispatch: DispatchFn, repo: BaseRepo, location: RepoLocation,
                  head: HeadRef, name: str, force: bool) -> bytes:
    """Remove a branch, refusing when the removal would lose commits.

    Args:
        dispatch (DispatchFn): workspace op dispatcher.
        repo (BaseRepo): the opened repository.
        location (RepoLocation): the discovered repository.
        head (HeadRef): what HEAD points at.
        name (str): the branch name.
        force (bool): whether ``-D`` was given, which deletes a branch
            HEAD does not contain.
    """
    ref = Ref(f"{HEADS_PREFIX.decode()}{name}".encode())
    if ref not in repo.refs.allkeys():
        raise NoBranchError(name)
    if name == head.branch:
        raise CheckedOutBranchError(name, location.worktree)
    sha = repo.refs[ref]
    if not force and not await asyncio.to_thread(_merged, repo, sha,
                                                 head_commit(repo, head)):
        raise UnmergedBranchError(name)
    await delete_ref(dispatch, location.commondir, ref.decode())
    return (f"Deleted branch {name} "
            f"(was {short(sha, abbrev_for(repo))}).\n").encode()


def _listed(repo: BaseRepo, local: bool, remote: bool,
            patterns: tuple[str, ...], filt: RefFilter | None) -> list[bytes]:
    """The refs a listing shows: the kinds ``-r``/``-a`` asked for,
    narrowed by the name patterns and the ref filter.

    A pattern matches the name as listed without its ``remotes/`` label
    (``origin/*``), which is git's reading, and any one pattern keeps a
    ref. Synchronous, for a worker thread: the filter walks history.

    Args:
        repo (BaseRepo): the opened repository.
        local (bool): whether local branches are listed.
        remote (bool): whether remote-tracking branches are listed.
        patterns (tuple[str, ...]): the name patterns, empty for all.
        filt (RefFilter | None): the resolved ref filter.
    """
    shown: list[bytes] = []
    for ref in sorted(repo.refs.allkeys()):
        is_local = ref.startswith(HEADS_PREFIX)
        if not (local and is_local) and not (remote and
                                             ref.startswith(REMOTES_PREFIX)):
            continue
        name = ref[len(HEADS_PREFIX if is_local else REMOTES_PREFIX):].decode()
        if patterns and not any(
                fnmatch.fnmatchcase(name, pattern) for pattern in patterns):
            continue
        shown.append(ref)
    if filt is None:
        return shown
    pairs: list[tuple[str, bytes]] = []
    for listed in shown:
        try:
            pairs.append((listed.decode(), repo.refs[Ref(listed)]))
        except KeyError:
            continue
    kept = kept_refs(repo, filt, pairs)
    return [listed for listed in shown if listed.decode() in kept]


async def branch(
        inv: CLIInvocation[None]) -> tuple[ByteSource | None, IOResult]:
    """List, create or delete branches.

    A name operand creates a branch, ``-d`` deletes one, and neither
    lists them with the checked-out one marked. ``-d`` deletes only a
    branch HEAD already contains, and ``-D`` deletes one regardless,
    which is git's own split and the reason both are here: without
    ``-D`` there is nothing ``-d`` can refuse to do. ``-r`` lists
    remote-tracking branches instead of local ones and ``-a`` lists
    both; local names sort together and remotes follow.

    ``-l`` and the ref filters (``--contains``, ``--merged``,
    ``--points-at`` and their negations) make the line a listing whose
    operands are name patterns, so ``git branch --contains side topic``
    lists ``topic`` if it holds ``side`` rather than creating anything,
    and a line that also deletes names two modes, which git answers
    with its usage.

    Args:
        inv (CLIInvocation[None]): the line's invocation record.
            git declares no config_model; the planes it reads
            (data through ``dispatch``, names through ``ns``) ride
            ``inv.doors``.
    """
    doors = inv.doors or CLIDoors()
    dispatch = doors.dispatch
    words = filter_words(inv)
    texts = without_filter_values(inv.texts, words)
    flags = inv.flags
    fl = FlagView(flags)
    remotes_only = fl.as_bool("r")
    include_remotes = remotes_only or fl.as_bool("a")
    listing = bool(words) or fl.as_bool("list")
    try:
        if dispatch is None:
            raise NoWorkspaceError()
        check_operands(texts, UnknownSwitchError, escaped(inv.argv),
                       switches(inv))
        repo, location = await opened(fl, doors)
        filt = await asyncio.to_thread(ref_filter, repo, words)
        head = await read_head(dispatch, location.gitdir)
        if fl.as_bool("show_current"):
            return ((head.branch +
                     "\n").encode() if head.branch else b""), IOResult()
        force = fl.as_bool("D")
        if fl.as_bool("delete") or force:
            if listing:
                raise BranchUsageError()
            if not texts:
                raise BranchNameRequiredError()
            deleted = b"".join([
                await _delete(dispatch, repo, location, head, name, force)
                for name in texts
            ])
            return yield_bytes(deleted), IOResult()
        if texts and not listing:
            tracking = await _create(dispatch, repo, location, texts[0],
                                     texts[1] if len(texts) > 1 else None)
            return yield_bytes(
                tracking.encode()) if tracking else None, IOResult()
        shown = await asyncio.to_thread(_listed, repo, not remotes_only,
                                        include_remotes, texts if listing else
                                        (), filt)
    except GitError as exc:
        return fatal(exc)
    verbose = fl.as_int("verbose") or 0
    cfg = await repo_config(inv, fl) if verbose else None
    width = max(
        (len(r[len(HEADS_PREFIX):].decode()) if r.startswith(HEADS_PREFIX) else
         len(REMOTE + r[len(REMOTES_PREFIX):].decode()) for r in shown),
        default=0)
    lines: list[str] = []
    if not remotes_only:
        for ref in (k for k in shown if k.startswith(HEADS_PREFIX)):
            name = ref[len(HEADS_PREFIX):].decode()
            marker = CURRENT if name == head.branch else OTHER
            detail = await asyncio.to_thread(_branch_detail, repo, ref, cfg,
                                             verbose) if verbose else ""
            lines.append(
                f"{marker}{name.ljust(width) if verbose else name}{detail}")
    if include_remotes:
        for ref in (k for k in shown if k.startswith(REMOTES_PREFIX)):
            name = ref[len(REMOTES_PREFIX):].decode()
            label = f"{REMOTE}{name}"
            suffix = _symref_suffix(repo, ref)
            detail = await asyncio.to_thread(
                _branch_detail, repo, ref, cfg,
                verbose) if verbose and not suffix else ""
            lines.append(f"{OTHER}{label.ljust(width) if detail else label}"
                         f"{suffix}{detail}")
    if not lines:
        return None, IOResult()
    return yield_bytes(("\n".join(lines) + "\n").encode()), IOResult()


def upstream_of(repo: BaseRepo, cfg: ConfigFile, branch: str,
                tip: ObjectID) -> Upstream | None:
    """A branch's upstream from ``branch.<name>.remote`` and ``.merge``.

    Args:
        repo (BaseRepo): the opened repository.
        cfg (ConfigFile): its config.
        branch (str): the branch's short name.
        tip (ObjectID): the commit the branch holds.
    """
    section = (b"branch", branch.encode())
    values = dict(cfg.items(section)) if cfg.has_section(section) else {}
    remote, merge = values.get(b"remote"), values.get(b"merge")
    if remote is None or merge is None:
        return None
    tracked = merge
    if remote != b".":
        tracked = (REMOTES_PREFIX + remote + b"/" +
                   merge.removeprefix(HEADS_PREFIX))
    label = tracked.removeprefix(HEADS_PREFIX).removeprefix(
        REMOTES_PREFIX).decode()
    if Ref(tracked) not in repo.refs.allkeys():
        return Upstream(label, 0, 0, True)
    ours = {e.commit.id for e in Walker(repo.object_store, [tip])}
    theirs = {
        e.commit.id
        for e in Walker(repo.object_store, [repo.refs[Ref(tracked)]])
    }
    return Upstream(label, len(ours - theirs), len(theirs - ours), False)


def _branch_detail(repo: BaseRepo, ref: bytes, cfg: ConfigFile | None,
                   verbose: int) -> str:
    commit = resolve_commit(repo, ref.decode())
    upstream = ""
    found = None
    if cfg is not None and ref.startswith(HEADS_PREFIX):
        found = upstream_of(repo, cfg, ref[len(HEADS_PREFIX):].decode(),
                            commit.id)
    if found is not None:
        differences = ["gone"] if found.gone else []
        if found.ahead:
            differences.append(f"ahead {found.ahead}")
        if found.behind:
            differences.append(f"behind {found.behind}")
        counts = ", ".join(differences)
        if verbose > 1:
            upstream = f" [{found.label}{': ' + counts if counts else ''}]"
        elif counts:
            upstream = f" [{counts}]"
    return f" {short(commit.id, abbrev_for(repo))}{upstream} {subject(commit)}"


async def branch_upstream(dispatch: DispatchFn, repo: BaseRepo,
                          location: RepoLocation, head: HeadRef,
                          no_commits: bool) -> Upstream | None:
    """The current branch's upstream, None when it has none or no commits.

    Args:
        dispatch (DispatchFn): workspace op dispatcher.
        repo (BaseRepo): the opened repository.
        location (RepoLocation): the discovered repository.
        head (HeadRef): what HEAD points at.
        no_commits (bool): whether the branch is still unborn.
    """
    if head.branch is None or no_commits:
        return None
    data = await read_optional(dispatch, f"{location.commondir}/config")
    cfg = ConfigFile.from_file(BytesIO(data or b""))
    ref = Ref(f"refs/heads/{head.branch}".encode())
    if (not cfg.has_section((b"branch", head.branch.encode()))
            or ref not in repo.refs.allkeys()):
        return None
    return await asyncio.to_thread(upstream_of, repo, cfg, head.branch,
                                   ObjectID(repo.refs[ref]))
