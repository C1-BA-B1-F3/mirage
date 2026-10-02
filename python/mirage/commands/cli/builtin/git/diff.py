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
from dataclasses import replace

from dulwich.repo import BaseRepo

from mirage.commands.cli.builtin.git.changes import head_entries
from mirage.commands.cli.builtin.git.constants import HEAD
from mirage.commands.cli.builtin.git.diff_output import (
    DiffFlags,
    compare,
    limited,
    parse_diff_flags,
    renames_enabled,
    render_changes,
    tree_output,
)
from mirage.commands.cli.builtin.git.errors import (
    GitError,
    InvalidOptionError,
    NoMergeBaseError,
    NoWorkspaceError,
)
from mirage.commands.cli.builtin.git.index_file import (
    read_index,
    refuse_unresolved,
)
from mirage.commands.cli.builtin.git.pathspec import pathspec_patterns
from mirage.commands.cli.builtin.git.repo import config_bool
from mirage.commands.cli.builtin.git.revparse import (
    merge_bases,
    range_commits,
    resolve_commit,
)
from mirage.commands.cli.builtin.git.session import opened
from mirage.commands.cli.builtin.git.tree import tree_entries
from mirage.commands.cli.builtin.git.types import IndexState
from mirage.commands.cli.builtin.git.util import (
    check_operands,
    escaped,
    fatal,
    split_marked,
    start_point,
)
from mirage.commands.cli.types import CLIDoors, CLIInvocation
from mirage.commands.spec.flag_view import FlagView
from mirage.io.stream import yield_bytes
from mirage.io.types import ByteSource, IOResult

# Deliberate divergence, verified against git 2.47.3 on a real
# repository. The patch is correct and applies cleanly, and file
# headers, mode lines, blob abbreviations and hunk function context
# match git exactly, but a hunk can still sit a line off where git's
# does (`@@ -3,6 +3,10 @@` against `@@ -4,6 +4,10 @@`): git slides a
# hunk to the equivalent boundary xdiff prefers (xdl_change_compact),
# so a blank line can be attributed to the additions on one side and
# the context on the other. Closing this means reimplementing that
# pass; until then do not claim byte parity for diff bodies. `log`,
# `log --oneline`, `show`'s header and `branch` ARE byte-identical.


def _sides(
    repo: BaseRepo, texts: tuple[str, ...]
) -> tuple[bytes, bytes, bytes]:
    """Resolve the two trees a diff compares, synchronously.

    One revision is compared with HEAD and two with each other.
    ``A..B`` is the two-revision form written as one operand, and
    ``A...B`` compares B with the merge base of the two, which is what
    a branch changed since it forked; with several bases git warns and
    takes the first (pinned against git 2.50).

    Runs on a worker thread, because resolving fetches through the
    dispatcher.

    Args:
        repo (BaseRepo): repository to read.
        texts (tuple[str, ...]): the revision operands, at least one.

    Returns:
        tuple[bytes, bytes, bytes]: the old tree, the new tree and any
            warning.
    """
    warning = b""
    ends = range_commits(repo, texts[0]) if len(texts) == 1 else None
    if ends is None:
        old = resolve_commit(repo, texts[0])
        new = resolve_commit(repo, texts[1] if len(texts) >= 2 else HEAD)
    else:
        old, new, symmetric = ends
        if symmetric:
            bases = merge_bases(repo, old, new)
            if not bases:
                raise NoMergeBaseError(texts[0])
            old = bases[0]
            if len(bases) > 1:
                warning = (
                    f"warning: {texts[0]}: multiple merge bases, "
                    f"using {old.id.decode()}\n"
                ).encode()
    return old.tree, new.tree, warning


def _base(
    repo: BaseRepo, texts: tuple[str, ...]
) -> dict[bytes, tuple[int, bytes]]:
    """The tree ``--cached`` compares the index with, synchronously.

    The named revision, HEAD by default, or the empty tree on an unborn
    branch.

    Args:
        repo (BaseRepo): repository to read.
        texts (tuple[str, ...]): optional base revision.
    """
    if len(texts) > 1:
        raise GitError("--cached accepts at most one revision")
    if texts:
        return tree_entries(
            repo.object_store, resolve_commit(repo, texts[0]).tree
        )
    return head_entries(repo) or {}


def _cached(
    repo: BaseRepo,
    before: dict[bytes, tuple[int, bytes]],
    state: IndexState,
    flags: DiffFlags,
) -> bytes:
    """Compare a commit tree with staged entries.

    Args:
        repo (BaseRepo): repository to read.
        before (dict[bytes, tuple[int, bytes]]): the base tree's entries.
        state (IndexState): staged entries.
        flags (DiffFlags): output options.
    """
    after: dict[bytes, tuple[int, bytes]] = {
        path: (entry.mode, entry.sha) for path, entry in state.entries.items()
    }
    return render_changes(
        repo,
        compare(
            repo,
            limited(before, flags.pathspecs),
            limited(after, flags.pathspecs),
            flags.renames,
        ),
        flags,
    )


async def diff(inv: CLIInvocation[None]) -> tuple[ByteSource | None, IOResult]:
    """Diff commits or compare staged content with a commit.

    One revision diffs it against HEAD's tree, two diff against each
    other. With --cached or --staged, compare the index with the named
    revision, HEAD by default, or the empty tree on an unborn branch.
    Operands after ``--`` are pathspecs, read once the revisions have
    resolved, as git reads them, and every format shows only the paths
    they name.

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
    cached = fl.as_bool("cached") or fl.as_bool("staged")
    revisions, paths = split_marked(tuple(texts), inv.argv)
    if not revisions and not cached and not paths:
        return None, IOResult()
    try:
        if dispatch is None:
            raise NoWorkspaceError()
        check_operands(texts, InvalidOptionError, escaped(inv.argv))
        repo, location = await opened(fl, doors)
        parsed = parse_diff_flags(
            fl,
            default_renames=await renames_enabled(dispatch, location),
            quote_path_fully=await config_bool(
                dispatch, location, b"core", b"quotepath", True
            ),
        )
        if not revisions and not cached:
            pathspec_patterns(location, start_point(fl), paths)
            return None, IOResult()
        if cached:
            state = await read_index(dispatch, location.gitdir)
            refuse_unresolved(state)
            before = await asyncio.to_thread(_base, repo, revisions)
            parsed = replace(
                parsed,
                pathspecs=pathspec_patterns(location, start_point(fl), paths),
            )
            body = await asyncio.to_thread(
                _cached, repo, before, state, parsed
            )
            warning = b""
        else:
            old, new, warning = await asyncio.to_thread(
                _sides, repo, revisions
            )
            parsed = replace(
                parsed,
                pathspecs=pathspec_patterns(location, start_point(fl), paths),
            )
            body = await asyncio.to_thread(tree_output, repo, old, new, parsed)
    except GitError as exc:
        return fatal(exc)
    result = IOResult(stderr=warning) if warning else IOResult()
    if not body:
        return None, result
    return yield_bytes(body), result
