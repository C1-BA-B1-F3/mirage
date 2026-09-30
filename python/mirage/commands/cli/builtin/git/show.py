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
from dataclasses import dataclass, replace

from dulwich.objects import Blob, Commit, Tree
from dulwich.repo import BaseRepo

from mirage.commands.cli.builtin.git.diff_output import (DiffFlags,
                                                         commit_output,
                                                         join_output,
                                                         parse_diff_flags,
                                                         renames_enabled)
from mirage.commands.cli.builtin.git.errors import GitError, NoWorkspaceError
from mirage.commands.cli.builtin.git.format import (Decorations, LogFormat,
                                                    needs_decorations, oneline,
                                                    preset_block,
                                                    render_template)
from mirage.commands.cli.builtin.git.history import decorations, pretty_format
from mirage.commands.cli.builtin.git.mailmap import (MailmapEntry,
                                                     load_mailmap, use_mailmap)
from mirage.commands.cli.builtin.git.objects import abbrev_for
from mirage.commands.cli.builtin.git.repo import config_bool
from mirage.commands.cli.builtin.git.revparse import (resolve_commit,
                                                      resolve_object)
from mirage.commands.cli.builtin.git.session import opened
from mirage.commands.cli.builtin.git.util import (  # yapf: disable
    check_operands, escaped, fatal, revision_arg)
from mirage.commands.cli.types import CLIDoors, CLIInvocation
from mirage.commands.spec.flag_view import FlagView
from mirage.io.stream import yield_bytes
from mirage.io.types import ByteSource, IOResult
from mirage.shell.bytes import encode_text


@dataclass(frozen=True, slots=True)
class ShowFlags:
    """The commit presentation and shared diff options."""
    diff: DiffFlags
    pretty: LogFormat
    date: str = "default"
    mailmap: tuple[MailmapEntry, ...] = ()
    use_mailmap: bool = True


def parse_show_flags(fl: FlagView,
                     default_renames: bool = True,
                     quote_path_fully: bool = True) -> ShowFlags:
    """Read the raw show flag kwargs into a frozen struct.

    Args:
        fl (FlagView): spec-validated view over the raw flag kwargs.
        default_renames (bool): ``diff.renames``.
        quote_path_fully (bool): ``core.quotePath``.
    """
    pretty = pretty_format(fl)
    return ShowFlags(
        diff=parse_diff_flags(fl,
                              default_merge="dense-combined",
                              default_renames=default_renames,
                              quote_path_fully=quote_path_fully),
        date=fl.as_str("date") or "default",
        pretty=pretty,
    )


def _header(commit: Commit, flags: ShowFlags, width: int,
            decor: Decorations | None) -> bytes:
    """The commit header in the requested format.

    ``format:`` is a separator, so a single commit prints with no
    trailing newline at all; ``tformat:`` terminates the entry even
    when it renders empty, except that an empty template prints
    nothing, matching ``log --format=``. Pinned against git 2.37 and
    2.54.

    Args:
        commit (Commit): the commit being shown.
        flags (ShowFlags): the parsed invocation.
        width (int): abbreviated id width for this repository.
        decor (Decorations | None): ref labels when the format asked.
    """
    fmt = flags.pretty
    if fmt.kind == "oneline":
        return f"{oneline(commit, width)}\n".encode()
    if fmt.kind in ("format", "tformat"):
        rendered = render_template(fmt.template or "", commit, width, decor,
                                   flags.date, flags.mailmap)
        if fmt.kind == "tformat":
            return encode_text(f"{rendered}\n") if fmt.template else b""
        return encode_text(rendered)
    return ("\n".join(
        preset_block(commit, fmt.kind, width, flags.date,
                     flags.mailmap if flags.use_mailmap else
                     ())) + "\n").encode()


def _render(repo: BaseRepo, revision: str, flags: ShowFlags,
            want_decor: bool) -> bytes:
    """Resolve a revision and render its entry and diff, synchronously.

    Runs on a worker thread: resolving, walking the tree and reading
    blobs all fetch through the dispatcher, so this must not sit on the
    loop that answers those fetches.

    Args:
        repo (BaseRepo): repository to read.
        revision (str): the revision to show.
        flags (ShowFlags): the parsed invocation.
        want_decor (bool): whether the format renders %d/%D.
    """
    obj = resolve_object(repo, revision)
    if isinstance(obj, Blob):
        return obj.data
    if isinstance(obj, Tree):
        return (f"tree {revision}\n\n".encode() +
                b"".join(name + (b"/" if mode == 0o40000 else b"") + b"\n"
                         for name, mode, _ in obj.iteritems()))
    commit = resolve_commit(repo, revision)
    decor = decorations(repo) if want_decor else None
    header = _header(commit, flags, abbrev_for(repo), decor)
    bodies = commit_output(repo, commit, flags.diff)
    return join_output(commit, header, bodies, flags.pretty.kind,
                       abbrev_for(repo), flags.diff, flags.diff.summary
                       and not flags.diff.no_patch)


async def show(inv: CLIInvocation[None]) -> tuple[ByteSource | None, IOResult]:
    """Show one commit: its log entry, then its diff against its parent.

    Args:
        inv (CLIInvocation[None]): the line's invocation record.
            git declares no config_model; the planes it reads
            (data through ``dispatch``, names through ``ns``) ride
            ``inv.doors``.
    """
    doors = inv.doors or CLIDoors()
    dispatch = doors.dispatch
    texts = inv.texts
    flags = inv.flags
    fl = FlagView(flags)
    try:
        if dispatch is None:
            raise NoWorkspaceError()
        check_operands(texts, marked=escaped(inv.argv))
        repo, location = await opened(fl, doors)
        parsed = parse_show_flags(
            fl, await renames_enabled(dispatch, location), await
            config_bool(dispatch, location, b"core", b"quotepath", True))
        parsed = replace(parsed,
                         mailmap=await load_mailmap(dispatch, location),
                         use_mailmap=use_mailmap(
                             fl, await config_bool(dispatch, location, b'log',
                                                   b'mailmap', True)))
        rendered = await asyncio.to_thread(_render, repo, revision_arg(texts),
                                           parsed,
                                           needs_decorations(parsed.pretty))
    except GitError as exc:
        return fatal(exc)
    return yield_bytes(rendered), IOResult()


def _diff_tree(repo: BaseRepo, revision: str, flags: DiffFlags,
               no_commit_id: bool, recursive: bool) -> bytes:
    commit = resolve_commit(repo, revision)
    bodies = commit_output(repo, commit, flags, recursive, root=False)
    return b"".join(
        (b"" if no_commit_id else commit.id + b"\n") + body for body in bodies)


async def diff_tree(
        inv: CLIInvocation[None]) -> tuple[ByteSource | None, IOResult]:
    fl = FlagView(inv.flags)
    doors = inv.doors or CLIDoors()
    try:
        if doors.dispatch is None:
            raise NoWorkspaceError()
        repo, location = await opened(fl, doors)
        fully = await config_bool(doors.dispatch, location, b"core",
                                  b"quotepath", True)
        out = await asyncio.to_thread(
            _diff_tree, repo, inv.texts[0] if inv.texts else "HEAD",
            parse_diff_flags(fl,
                             default_patch=False,
                             porcelain=False,
                             quote_path_fully=fully),
            fl.as_bool("no_commit_id"), fl.as_bool("r"))
        return out, IOResult()
    except GitError as exc:
        return fatal(exc)
