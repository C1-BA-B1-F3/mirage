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
import posixpath
from dataclasses import dataclass

from dulwich.objects import Tag
from dulwich.refs import Ref
from dulwich.repo import BaseRepo

from mirage.commands.cli.builtin.git.branch import branch_upstream
from mirage.commands.cli.builtin.git.changes import collect
from mirage.commands.cli.builtin.git.constants import DWIM_RULES
from mirage.commands.cli.builtin.git.errors import GitError, NoWorkspaceError
from mirage.commands.cli.builtin.git.format import short
from mirage.commands.cli.builtin.git.io import read_optional
from mirage.commands.cli.builtin.git.objects import abbrev_for
from mirage.commands.cli.builtin.git.pathspec import repo_relative
from mirage.commands.cli.builtin.git.refs import read_head
from mirage.commands.cli.builtin.git.render import (DETACHED_AT, DETACHED_FROM,
                                                    NO_BRANCH, branch_line,
                                                    long_format,
                                                    relative_entries,
                                                    short_format)
from mirage.commands.cli.builtin.git.repo import config_bool
from mirage.commands.cli.builtin.git.session import opened
from mirage.commands.cli.builtin.git.types import (HeadRef, RepoLocation,
                                                   StatusEntry)
from mirage.commands.cli.builtin.git.util import fatal, links_of, start_point
from mirage.commands.cli.builtin.git.worktree import (UNTRACKED_ALL,
                                                      UNTRACKED_NO,
                                                      UNTRACKED_NORMAL)
from mirage.commands.cli.types import CLIDoors, CLIInvocation
from mirage.commands.spec.flag_view import FlagView
from mirage.io.stream import yield_bytes
from mirage.io.types import ByteSource, IOResult
from mirage.ops.types import LinkView, StatPath
from mirage.runtime.types import DispatchFn


@dataclass(frozen=True, slots=True)
class StatusFlags:
    """The parsed shape of a ``git status`` invocation.

    Args:
        porcelain (bool): ``--porcelain``, the stable machine format.
        short (bool): ``-s``, the same rows meant for a person.
        branch (bool): ``-b``, prepend the ``##`` branch line.
        untracked (str): ``-u``, which untracked files to report.
    """
    porcelain: bool
    short: bool
    branch: bool
    untracked: str
    ignored: bool = False


def parse_flags(fl: FlagView) -> StatusFlags:
    """Read the raw status flag kwargs into a frozen struct.

    ``-u`` carries its mode attached or not at all, and a bare one means
    ``all``, which is why the value is read as a string first and only
    then as a boolean.

    Args:
        fl (FlagView): spec-validated view over the raw flag kwargs.
    """
    mode = fl.as_str("untracked_files")
    if mode is None:
        mode = UNTRACKED_ALL if fl.as_bool(
            "untracked_files") else UNTRACKED_NORMAL
    version = fl.as_str("porcelain")
    if version is not None and version not in ("1", "v1"):
        raise GitError(f"unsupported porcelain version '{version}'")
    return StatusFlags(porcelain=fl.as_bool("porcelain")
                       or version is not None,
                       short=fl.as_bool("short"),
                       branch=fl.as_bool("branch"),
                       untracked=mode,
                       ignored=fl.as_bool("ignored"))


async def displayed(dispatch: DispatchFn, location: RepoLocation, start: str,
                    rows: list[StatusEntry]) -> list[StatusEntry]:
    """Status rows as a person reads them, relative to where git runs.

    git's human formats name paths from the invocation directory unless
    ``status.relativePaths`` is false; porcelain never does. From outside
    the work tree they stay relative to its root.

    Args:
        dispatch (DispatchFn): workspace op dispatcher.
        location (RepoLocation): the discovered repository.
        start (str): absolute virtual path git is running in.
        rows (list[StatusEntry]): repository-relative status entries.
    """
    if not await config_bool(dispatch, location, b"status", b"relativepaths",
                             True):
        return rows
    return relative_entries(rows, repo_relative(location, start, "."))


CHECKOUT_MOVE = "checkout: moving from "


def _detached_label(repo: BaseRepo, target: str, moved: bytes) -> str:
    """How the status names where a detached HEAD came from.

    The checkout's target when it still names exactly one ref holding
    that commit (a tag or remote-tracking branch by its short name), the
    abbreviated id otherwise.

    Args:
        repo (BaseRepo): the opened repository.
        target (str): what the checkout was asked for.
        moved (bytes): the commit it moved HEAD to.
    """
    refs = repo.refs.allkeys()
    found = [
        name for name in dict.fromkeys(
            rule.format(target) for rule in DWIM_RULES)
        if name.encode() in refs
    ]
    if target != "HEAD" and len(found) == 1:
        obj = repo.object_store[repo.refs[Ref(found[0].encode())]]
        while isinstance(obj, Tag):
            obj = repo.object_store[obj.object[1]]
        if obj.id == moved:
            return found[0].removeprefix("refs/tags/").removeprefix(
                "refs/remotes/")
    return short(moved, abbrev_for(repo))


async def detached_line(dispatch: DispatchFn, repo: BaseRepo,
                        location: RepoLocation, head: HeadRef) -> str:
    """The first line of a status on a detached HEAD, read off the reflog.

    git names the target of the newest ``checkout: moving from`` entry,
    ``at`` while HEAD is still there and ``from`` once it has moved on,
    and says it is on no branch when no checkout put it there, which is
    what a clone of a tag or of a detached HEAD reads (pinned against
    git 2.47.3 and 2.50.1).

    Args:
        dispatch (DispatchFn): workspace op dispatcher.
        repo (BaseRepo): the opened repository.
        location (RepoLocation): the discovered repository.
        head (HeadRef): what HEAD points at.
    """
    log = await read_optional(dispatch,
                              posixpath.join(location.gitdir, "logs/HEAD"))
    for row in reversed((log or b"").splitlines()):
        record, _, message = row.partition(b"\t")
        text = message.decode("utf-8", "replace")
        if not text.startswith(CHECKOUT_MOVE) or " to " not in text:
            continue
        target = text[len(CHECKOUT_MOVE):].split(" to ", 1)[1]
        moved = record.split(b" ")[1]
        label = await asyncio.to_thread(_detached_label, repo, target, moved)
        at = head.commit is not None and head.commit.encode() == moved
        return f"{DETACHED_AT if at else DETACHED_FROM}{label}"
    return NO_BRANCH


async def render_report(dispatch: DispatchFn,
                        stat_path: StatPath,
                        repo: BaseRepo,
                        location: RepoLocation,
                        head: HeadRef,
                        start: str,
                        links: LinkView | None = None) -> str:
    """The default status report, as a string.

    Split out so ``commit`` can print it when it has nothing to commit:
    git shows the whole status there rather than a one-line refusal, and
    two renderings of the same thing would drift.

    Args:
        dispatch (DispatchFn): workspace op dispatcher.
        stat_path (StatPath): dispatcher-backed stat, both channels.
        repo (BaseRepo): the opened repository.
        location (RepoLocation): the discovered repository.
        head (HeadRef): what HEAD points at.
        start (str): absolute virtual path git is running in, which the
            report's paths are relative to.
        links (LinkView | None): the name plane's link facts, so the
            walk lstats as git does.
    """
    rows, state, no_commits = await collect(dispatch, stat_path, repo,
                                            location, UNTRACKED_NORMAL, links)
    fully = await config_bool(dispatch, location, b"core", b"quotepath", True)
    detached = "" if head.branch is not None else await detached_line(
        dispatch, repo, location, head)
    upstream = await branch_upstream(dispatch, repo, location, head,
                                     no_commits)
    return long_format(await displayed(dispatch, location, start,
                                       rows), head.branch, detached,
                       no_commits, state.merging, False, fully, upstream)


async def status(
        inv: CLIInvocation[None]) -> tuple[ByteSource | None, IOResult]:
    """Show the working tree status.

    Three sources, compared pairwise: HEAD's tree against the index says
    what a commit would record, and the index against the working tree
    says what it would leave behind. Everything the report prints is one
    of those two answers, or a path neither side knows about.

    Args:
        inv (CLIInvocation[None]): the line's invocation record.
            git declares no config_model; the planes it reads
            (data through ``dispatch``, names through ``ns``) ride
            ``inv.doors``.
    """
    doors = inv.doors or CLIDoors()
    dispatch = doors.dispatch
    stat_path = doors.stat_path
    flags = inv.flags
    fl = FlagView(flags)
    try:
        if dispatch is None or stat_path is None:
            raise NoWorkspaceError()
        parsed = parse_flags(fl)
        repo, location = await opened(fl, doors, work_tree=True)
        head = await read_head(dispatch, location.gitdir)
        rows, state, no_commits = await collect(dispatch, stat_path, repo,
                                                location, parsed.untracked,
                                                links_of(doors),
                                                parsed.ignored)
        fully = await config_bool(dispatch, location, b"core", b"quotepath",
                                  True)
        if not parsed.porcelain:
            rows = await displayed(dispatch, location, start_point(fl), rows)
        upstream = await branch_upstream(dispatch, repo, location, head,
                                         no_commits)
        detached = "" if head.branch is not None else await detached_line(
            dispatch, repo, location, head)
    except GitError as exc:
        return fatal(exc)
    if parsed.porcelain or parsed.short:
        header = branch_line(head.branch, no_commits,
                             upstream) if parsed.branch else None
        body = short_format(rows, header, fully)
    else:
        body = long_format(rows, head.branch, detached, no_commits,
                           state.merging, parsed.untracked == UNTRACKED_NO,
                           fully, upstream)
    return yield_bytes(body.encode()), IOResult()
