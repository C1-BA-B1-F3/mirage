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

from dataclasses import dataclass, replace
from difflib import SequenceMatcher
from io import BytesIO

from dulwich.config import ConfigFile
from dulwich.diff_tree import _similarity_score
from dulwich.objects import Blob, Commit, ObjectID, Tree
from dulwich.repo import BaseRepo

from mirage.commands.cli.builtin.git.changes import pair_renames
from mirage.commands.cli.builtin.git.combined import combined_lines
from mirage.commands.cli.builtin.git.constants import FUNCNAME_START, GIT_SPACE
from mirage.commands.cli.builtin.git.errors import GitError
from mirage.commands.cli.builtin.git.io import read_optional
from mirage.commands.cli.builtin.git.objects import abbrev_for
from mirage.commands.cli.builtin.git.render import quote_path
from mirage.commands.cli.builtin.git.summary import (BINARY_SNIFF, FileStat,
                                                     diffstat, stat_table,
                                                     tree_entries)
from mirage.commands.cli.builtin.git.types import RepoLocation
from mirage.commands.spec.flag_view import FlagView
from mirage.runtime.types import DispatchFn
from mirage.shell.bytes import encode_text

OID_HEX = 40
DEV_NULL = '/dev/null'
HUNK_CONTEXT = 3
FUNCNAME_BYTES = 80
HUNK_HEADER_BYTES = 128
RENAME_SCORE = 50


@dataclass(frozen=True, slots=True)
class DiffFlags:
    """One interpretation of Git diff options, shared by all tree readers."""
    name_only: bool = False
    name_status: bool = False
    stat: bool = False
    numstat: bool = False
    shortstat: bool = False
    summary: bool = False
    patch: bool = False
    no_patch: bool = False
    renames: int | None = None
    merge: str = 'off'
    raw: bool = False
    abbrev: bool = False
    context: int = HUNK_CONTEXT
    quote_path_fully: bool = True


def parse_diff_flags(fl: FlagView,
                     *,
                     default_patch: bool = True,
                     default_merge: str = 'off',
                     porcelain: bool = True,
                     default_renames: bool = True,
                     quote_path_fully: bool = True) -> DiffFlags:
    modes = [
        fl.as_bool(key) for key in ('name_only', 'name_status', 'stat',
                                    'numstat', 'shortstat', 'summary', 'raw')
    ]
    rename = fl.raw('find_renames')
    threshold = None
    if rename is not None and rename is not False:
        threshold = RENAME_SCORE
        if isinstance(rename, str) and rename:
            value = rename.removesuffix('%')
            try:
                threshold = int(value) if rename.endswith('%') else int(
                    float('0.' + value) * 100)
            except ValueError as exc:
                raise GitError(f'invalid similarity index {rename}') from exc
    elif porcelain and default_renames:
        threshold = RENAME_SCORE
    if fl.as_bool('no_renames'):
        threshold = None
    merge = fl.as_str('diff_merges') or default_merge
    if fl.as_bool('m'):
        merge = 'separate'
    if fl.as_bool('c'):
        merge = 'combined'
    if fl.as_bool('cc'):
        merge = 'dense-combined'
    if porcelain and fl.as_bool('first_parent'):
        merge = 'first-parent'
    merge = {
        '0': 'off',
        '1': 'separate',
        'on': 'separate',
        'm': 'separate',
        'c': 'combined',
        'cc': 'dense-combined'
    }.get(merge, merge)
    if merge not in ('off', 'separate', 'combined', 'dense-combined',
                     'first-parent'):
        raise GitError(f'invalid value for --diff-merges: {merge}')
    context = fl.as_int("unified")
    if context is not None and context < 0:
        raise GitError("negative context length")
    patch = fl.as_bool("patch") or context is not None or (
        (default_patch or fl.as_bool("cc") or
         (porcelain and fl.as_bool("c"))) and not any(modes))
    return DiffFlags(context=HUNK_CONTEXT if context is None else context,
                     name_only=modes[0],
                     name_status=modes[1],
                     stat=modes[2],
                     numstat=modes[3],
                     shortstat=modes[4],
                     summary=modes[5],
                     patch=patch,
                     no_patch=fl.as_bool('no_patch'),
                     renames=threshold,
                     merge=merge,
                     raw=modes[6]
                     or not porcelain and not any(modes) and not patch,
                     abbrev=porcelain,
                     quote_path_fully=quote_path_fully)


@dataclass(frozen=True, slots=True)
class Change:
    """A paired tree delta; every output format consumes these same rows."""
    path: bytes
    old_path: bytes
    old: tuple[int, bytes] | None
    new: tuple[int, bytes] | None
    status: str
    score: int = 0


def compare(repo: BaseRepo, before: dict[bytes, tuple[int, bytes]],
            after: dict[bytes, tuple[int, bytes]],
            threshold: int | None) -> list[Change]:
    changed = sorted(p for p in set(before) | set(after)
                     if before.get(p) != after.get(p))
    names = {p.decode('utf-8', errors='surrogateescape'): p for p in changed}
    codes = {
        name: ('A' if p not in before else
               'D' if p not in after else 'T' if before[p][0]
               & 0o170000 != after[p][0] & 0o170000 else 'M')
        for name, p in names.items()
    }
    entries = {name: after.get(p, before.get(p)) for name, p in names.items()}
    pairs = {
        p: (code, None)
        for p, code in codes.items()
    } if threshold is None else pair_renames(repo.object_store, codes, {
        p: e[1]
        for p, e in entries.items() if e is not None
    }, {
        p: e[0] & 0o170000
        for p, e in entries.items() if e is not None
    }, threshold)
    rows = []
    for path, (status, origin) in sorted(pairs.items(),
                                         key=lambda item: names[item[0]]):
        name, old_path = names[path], names[origin or path]
        old, new = before.get(old_path), after.get(name)
        score = 0
        if origin is not None and old is not None and new is not None:
            score = 100 if old[1] == new[1] else _similarity_score(
                repo.object_store[ObjectID(old[1])],
                repo.object_store[ObjectID(new[1])])
        rows.append(Change(name, old_path, old, new, status, score))
    return rows


def rename_name(old: str, new: str, fully: bool = True) -> str:
    """How a rename names its paths in a diffstat, git's pprint_rename.

    When either side needs quoting the two quoted paths stand whole;
    otherwise the shared leading and trailing directories fold into
    ``pre/{old => new}/post``.

    Args:
        old (str): the source path, surrogate-escaped.
        new (str): the destination path, surrogate-escaped.
        fully (bool): ``core.quotePath``.
    """
    quoted_old = quote_path(old, False, fully)
    quoted_new = quote_path(new, False, fully)
    if quoted_old != old or quoted_new != new:
        return f'{quoted_old} => {quoted_new}'
    a, b = old.split('/'), new.split('/')
    prefix = []
    while len(a) > 1 and len(b) > 1 and a[0] == b[0]:
        prefix.append(a.pop(0))
        b.pop(0)
    suffix: list[str] = []
    while len(a) > 1 and len(b) > 1 and a[-1] == b[-1]:
        suffix.insert(0, a.pop())
        b.pop()
    middle = '/'.join(a) + ' => ' + '/'.join(b)
    return '/'.join([*prefix, '{' + middle +
                     '}', *suffix]) if prefix or suffix else middle


def render_changes(repo: BaseRepo, rows: list[Change],
                   flags: DiffFlags) -> bytes:
    """Every requested format for one two-tree comparison, in git's order.

    ``--name-only`` and ``--name-status`` stand alone; otherwise raw
    rows come first, then numstat, stat and summary, then a blank line
    and the patch.

    Args:
        repo (BaseRepo): repository to read blobs from.
        rows (list[Change]): the paired tree deltas.
        flags (DiffFlags): the parsed invocation.
    """
    if flags.no_patch:
        return b''
    width = abbrev_for(repo) if flags.abbrev else OID_HEX
    fully = flags.quote_path_fully
    lines: list[str] = []
    stats: list[FileStat] = []
    numbers: list[str] = []
    summaries: list[str] = []
    patches: list[bytes] = []
    for row in rows:
        name = row.path.decode('utf-8', errors='surrogateescape')
        origin = row.old_path.decode('utf-8', errors='surrogateescape')
        shown = quote_path(name, False, fully)
        status = f'R{row.score:03d}' if row.status == 'R' else row.status
        paths = (f'{quote_path(origin, False, fully)}\t{shown}'
                 if row.status == 'R' else shown)
        if flags.name_only:
            lines.append(shown)
            continue
        if flags.name_status:
            lines.append(f'{status}\t{paths}')
            continue
        if flags.raw:
            lines.append(f':{_mode(row.old):06o} {_mode(row.new):06o} '
                         f'{_short(row.old, width)} {_short(row.new, width)} '
                         f'{status}\t{paths}')
        display = (rename_name(origin, name, fully)
                   if row.status == 'R' else shown)
        if flags.stat or flags.numstat or flags.shortstat:
            stats.append(_row_stat(repo, row, display))
        if flags.numstat:
            counts = ('-\t-' if stats[-1].binary else
                      f'{stats[-1].insertions}\t{stats[-1].deletions}')
            numbers.append(f'{counts}\t{display}')
        if flags.summary:
            summaries.extend(_summary(row, display, shown))
        if flags.patch:
            patches.append(
                file_patch(repo, row, name, origin, abbrev_for(repo), fully,
                           flags.context))
    if not (flags.name_only or flags.name_status):
        table = stat_table(stats)
        lines += numbers + (table if flags.stat else
                            table[-1:] if flags.shortstat else []) + summaries
    output = encode_text(''.join(line + '\n' for line in lines))
    body = b''.join(patches)
    return output + (b'\n' if output and body else b'') + body


def commit_summary(repo: BaseRepo,
                   before: dict[bytes, tuple[int, bytes]],
                   after: dict[bytes, tuple[int, bytes]],
                   fully: bool = True) -> bytes:
    """The counts and summary lines ``git commit`` prints under its title.

    ``--shortstat --summary`` of the change, with renames found at git's
    default score whatever ``diff.renames`` says, which is how git's
    commit summary reads (pinned against git 2.50).

    Args:
        repo (BaseRepo): repository to read blobs from.
        before (dict): the parent tree, path to (mode, blob id).
        after (dict): the new tree, path to (mode, blob id).
        fully (bool): ``core.quotePath``.
    """
    return render_changes(
        repo, compare(repo, before, after, RENAME_SCORE),
        DiffFlags(shortstat=True, summary=True, quote_path_fully=fully))


def _mode(entry: tuple[int, bytes] | None) -> int:
    """An entry's mode, zero for the side that does not exist.

    Args:
        entry (tuple[int, bytes] | None): the (mode, id) pair or None.
    """
    return entry[0] if entry else 0


def _short(entry: tuple[int, bytes] | None, width: int) -> str:
    """An entry's object id cut to ``width``, zeros for a missing side.

    Args:
        entry (tuple[int, bytes] | None): the (mode, id) pair or None.
        width (int): how many hex digits to keep.
    """
    return (entry[1].decode() if entry else '0' * OID_HEX)[:width]


def _row_stat(repo: BaseRepo, row: Change, display: str) -> FileStat:
    """The diffstat row for one change, named the way git prints it.

    Args:
        repo (BaseRepo): repository to read blobs from.
        row (Change): the paired delta.
        display (str): the quoted or rename-folded name.
    """
    before = {row.path: row.old} if row.old else {}
    after = {row.path: row.new} if row.new else {}
    counted = diffstat(repo.object_store, before, after)
    if counted:
        return replace(counted[0], path=display)
    fresh = diffstat(repo.object_store, {}, after)[0]
    return replace(fresh,
                   path=display,
                   insertions=0,
                   deletions=0,
                   old_size=fresh.new_size)


def _summary(row: Change, display: str, shown: str) -> list[str]:
    """The ``--summary`` lines for one change, git's diff_summary.

    Args:
        row (Change): the paired delta.
        display (str): the rename-folded name.
        shown (str): the quoted destination path.
    """
    old, new = row.old, row.new
    if row.status == 'R':
        lines = [f' rename {display} ({row.score}%)']
        if old and new and old[0] != new[0]:
            lines.append(f' mode change {old[0]:06o} => {new[0]:06o}')
        return lines
    if old is None and new:
        return [f' create mode {new[0]:06o} {shown}']
    if new is None and old:
        return [f' delete mode {old[0]:06o} {shown}']
    if old and new and old[0] != new[0]:
        return [f' mode change {old[0]:06o} => {new[0]:06o} {shown}']
    return []


def file_patch(repo: BaseRepo,
               row: Change,
               name: str,
               origin: str,
               width: int,
               fully: bool = True,
               context: int = HUNK_CONTEXT) -> bytes:
    """One path's patch, headers and hunks, as git's builtin_diff writes it.

    A change between a file and a symlink is split into a deletion and
    a creation, the way git's run_diff splits a type change. A ``---``
    or ``+++`` label holding a space ends in a tab, so a patch tool can
    tell where the name stops.

    Args:
        repo (BaseRepo): repository to read blobs from.
        row (Change): the paired delta.
        name (str): the destination path, surrogate-escaped.
        origin (str): the source path, surrogate-escaped.
        width (int): how many hex digits the index line keeps.
        fully (bool): ``core.quotePath``.
        context (int): the requested number of context lines.
    """
    old, new = row.old, row.new
    if old and new and old[0] & 0o170000 != new[0] & 0o170000:
        return (file_patch(repo, replace(row, new=None), name, origin, width,
                           fully, context) +
                file_patch(repo, replace(row, old=None), name, origin, width,
                           fully, context))
    source = quote_path(f'a/{origin}', False, fully)
    target = quote_path(f'b/{name}', False, fully)
    head = [f'diff --git {source} {target}']
    if old is None and new:
        head.append(f'new file mode {new[0]:06o}')
    elif new is None and old:
        head.append(f'deleted file mode {old[0]:06o}')
    elif old and new and old[0] != new[0]:
        head += [f'old mode {old[0]:06o}', f'new mode {new[0]:06o}']
    if row.status == 'R':
        head += [
            f'similarity index {row.score}%',
            f'rename from {quote_path(origin, False, fully)}',
            f'rename to {quote_path(name, False, fully)}'
        ]
    if old and new and old[1] == new[1]:
        return encode_text(''.join(line + '\n' for line in head))
    index = f'index {_short(old, width)}..{_short(new, width)}'
    if old and new and old[0] == new[0]:
        index += f' {old[0]:06o}'
    head.append(index)
    before, after = blob_data(repo, old), blob_data(repo, new)
    source = source if old else DEV_NULL
    target = target if new else DEV_NULL
    if any(b'\0' in data[:BINARY_SNIFF] for data in (before, after)):
        head.append(f'Binary files {source} and {target} differ')
        return encode_text(''.join(line + '\n' for line in head))
    body = hunks(byte_lines(before), byte_lines(after), context)
    if body:
        head += [
            f'--- {source}' + ('\t' if ' ' in source else ''),
            f'+++ {target}' + ('\t' if ' ' in target else '')
        ]
    return encode_text(''.join(line + '\n' for line in head)) + body


def byte_lines(data: bytes) -> list[bytes]:
    """Split a blob at each newline only, keeping them, as xdiff does.

    Args:
        data (bytes): the blob's bytes.
    """
    *whole, rest = data.split(b'\n')
    return [line + b'\n' for line in whole] + ([rest] if rest else [])


def hunks(old: list[bytes],
          new: list[bytes],
          count: int = HUNK_CONTEXT) -> bytes:
    """The ``@@`` hunks of a two-way patch, as xdiff's xdl_emit_diff emits.

    Each header carries the nearest earlier line of the old side that
    starts with a letter, ``_`` or ``$`` (git's default funcname), and
    keeps the previous hunk's when none lies between the two.

    Args:
        old (list[bytes]): the old side's lines, newlines kept.
        new (list[bytes]): the new side's lines, newlines kept.
        count (int): the requested number of context lines.
    """
    out = []
    context = b''
    searched = -1
    for group in SequenceMatcher(a=old, b=new,
                                 autojunk=False).get_grouped_opcodes(count):
        start, stop = group[0][1], group[-1][2]
        found = next((old[k] for k in range(start - 1, searched, -1)
                      if old[k] and chr(old[k][0]) in FUNCNAME_START), None)
        searched = start - 1
        if found is not None:
            context = found[:FUNCNAME_BYTES].rstrip(GIT_SPACE)
        head = (f'@@ -{_span(start, stop)} '
                f'+{_span(group[0][3], group[-1][4])} @@').encode()
        if context:
            head += b' ' + context[:HUNK_HEADER_BYTES - len(head) - 2]
        out.append(head + b'\n')
        for tag, i1, i2, j1, j2 in group:
            if tag == 'equal':
                out.extend(_hunk_line(b' ', line) for line in old[i1:i2])
                continue
            out.extend(_hunk_line(b'-', line) for line in old[i1:i2])
            out.extend(_hunk_line(b'+', line) for line in new[j1:j2])
    return b''.join(out)


def _span(start: int, stop: int) -> str:
    """A hunk range: ``start,count``, the count dropped when it is one.

    Args:
        start (int): the first line, counted from zero.
        stop (int): one past the last line.
    """
    if stop - start == 1:
        return str(start + 1)
    return f'{start + 1 if stop > start else start},{stop - start}'


def _hunk_line(marker: bytes, line: bytes) -> bytes:
    """One hunk line, with git's marker when it has no newline.

    Args:
        marker (bytes): ``b' '``, ``b'-'`` or ``b'+'``.
        line (bytes): the line, with its newline when it has one.
    """
    if line.endswith(b'\n'):
        return marker + line
    return marker + line + b'\n\\ No newline at end of file\n'


def entries(repo: BaseRepo, tree: bytes | None,
            recursive: bool) -> dict[bytes, tuple[int, bytes]]:
    if recursive or tree is None:
        return tree_entries(repo.object_store, tree)
    obj = repo.object_store[ObjectID(tree)]
    assert isinstance(obj, Tree)
    return {entry.path: (entry.mode, entry.sha) for entry in obj.iteritems()}


def tree_output(repo: BaseRepo,
                before: bytes | None,
                after: bytes,
                flags: DiffFlags,
                recursive: bool = True) -> bytes:
    return render_changes(
        repo,
        compare(repo, entries(repo, before, recursive),
                entries(repo, after, recursive), flags.renames), flags)


def commit_output(repo: BaseRepo,
                  commit: Commit,
                  flags: DiffFlags,
                  recursive: bool = True,
                  root: bool = True) -> list[bytes]:
    parents = [repo.object_store[p] for p in commit.parents]
    assert all(isinstance(p, Commit) for p in parents)
    trees = [p.tree for p in parents if isinstance(p, Commit)]
    if not trees:
        return [tree_output(repo, None, commit.tree, flags, recursive)
                ] if root else []
    if len(trees) == 1 or flags.merge == 'first-parent':
        return [tree_output(repo, trees[0], commit.tree, flags, recursive)]
    if flags.merge == 'off':
        return []
    if flags.merge == 'separate':
        return [
            tree_output(repo, tree, commit.tree, flags, recursive)
            for tree in trees
        ]
    after = entries(repo, commit.tree, recursive)
    comparisons = [
        compare(repo, entries(repo, tree, recursive), after, flags.renames)
        for tree in trees
    ]
    common = set.intersection(*({row.path
                                 for row in rows} for rows in comparisons))
    maps = [{row.path: row for row in rows} for rows in comparisons]
    if flags.no_patch:
        return []
    width = abbrev_for(repo) if flags.abbrev else OID_HEX
    names = flags.name_only or flags.name_status
    stat = render_changes(
        repo, comparisons[0], replace(
            flags, patch=False, raw=False)) if (not names and any(
                (flags.stat, flags.numstat, flags.shortstat,
                 flags.summary))) else b''
    lines = []
    for path in sorted(common) if names or flags.raw else []:
        status = ''.join(m[path].status for m in maps)
        shown = quote_path(path.decode('utf-8', errors='surrogateescape'),
                           False, flags.quote_path_fully)
        if flags.name_only:
            lines.append(shown)
        elif flags.name_status:
            lines.append(f'{status}\t{shown}')
        else:
            sides = [*(m[path].old for m in maps), maps[0][path].new]
            lines.append(':' * len(maps) + ' '.join(f'{_mode(e):06o}'
                                                    for e in sides) + ' ' +
                         ' '.join(_short(e, width)
                                  for e in sides) + f' {status}\t{shown}')
    head = stat + encode_text(''.join(line + '\n' for line in lines))
    patch = combined_patch(repo, maps, common, flags.merge == 'dense-combined',
                           flags.quote_path_fully,
                           flags.context) if flags.patch and not names else b''
    return [head + (b'\n' if head and patch else b'') + patch]


def combined_patch(repo: BaseRepo,
                   maps: list[dict[bytes, Change]],
                   paths: set[bytes],
                   dense: bool,
                   fully: bool = True,
                   context: int = HUNK_CONTEXT) -> bytes:
    """Render ``-c``/``--cc`` for the paths that differ from every parent.

    A path with no hunk left and no mode change prints nothing at all,
    and the headers follow git's show_combined_header.

    Args:
        repo (BaseRepo): repository to read blobs from.
        maps (list[dict[bytes, Change]]): per parent, its rows by path.
        paths (set[bytes]): the paths changed against every parent.
        dense (bool): ``--cc`` rather than ``-c``.
        fully (bool): ``core.quotePath``.
        context (int): the requested number of context lines.
    """
    out = []
    for path in sorted(paths):
        changes = [m[path] for m in maps]
        new = changes[0].new
        old = [row.old for row in changes]
        new_data = blob_data(repo, new)
        old_data = [blob_data(repo, entry) for entry in old]
        binary = any(b'\0' in data[:8000] for data in [*old_data, new_data])
        body = [] if binary else combined_lines(
            [text_lines(data)
             for data in old_data], text_lines(new_data), dense, context)
        mode = new[0] if new else 0
        moved = any((entry[0] if entry else 0) != mode for entry in old)
        if not (binary or body or moved):
            continue
        deleted = new is None
        created = not deleted and all(row.status == 'A' for row in changes)
        name = path.decode('utf-8', errors='surrogateescape')
        width = abbrev_for(repo)
        out.append(f'diff --{"cc" if dense else "combined"} '
                   f'{quote_path(name, False, fully)}\n')
        out.append('index ' + ','.join(_short(entry, width) for entry in old) +
                   '..' + _short(new, width) + '\n')
        if moved and created:
            out.append(f'new file mode {mode:06o}\n')
        elif moved:
            out.append(('deleted file mode ' if deleted else 'mode ') +
                       ','.join(f'{entry[0] if entry else 0:06o}'
                                for entry in old) +
                       ('' if deleted else f'..{mode:06o}') + '\n')
        if binary:
            out.append('Binary files differ\n')
            continue
        out.append('--- ' + (
            DEV_NULL if created else quote_path(f'a/{name}', False, fully)) +
                   '\n')
        out.append('+++ ' + (
            DEV_NULL if deleted else quote_path(f'b/{name}', False, fully)) +
                   '\n')
        out.extend(body)
    return encode_text(''.join(out))


def text_lines(data: bytes) -> list[str]:
    """Split a blob at each newline only, the way git does, keeping them.

    Args:
        data (bytes): the blob's bytes.
    """
    *whole, rest = data.decode('utf-8', errors='replace').split('\n')
    return [line + '\n' for line in whole] + ([rest] if rest else [])


def blob_data(repo: BaseRepo, entry: tuple[int, bytes] | None) -> bytes:
    if entry is None:
        return b''
    if entry[0] == 0o160000:
        return b'Subproject commit ' + entry[1] + b'\n'
    obj = repo.object_store[ObjectID(entry[1])]
    assert isinstance(obj, Blob)
    return obj.data


async def renames_enabled(dispatch: DispatchFn,
                          location: RepoLocation) -> bool:
    data = await read_optional(dispatch, f"{location.commondir}/config")
    if data is None:
        return True
    cfg = ConfigFile.from_file(BytesIO(data))
    try:
        value = cfg.get((b"diff", ), b"renames")
    except KeyError:
        return True
    return value.lower() not in (b"false", b"no", b"off", b"0", b"")


def separator_line(commit: Commit, kind: str, flags: DiffFlags) -> str | None:
    """The line git prints between a commit's text and its diff, None
    for none.

    ``---`` when both a diffstat and a patch follow, otherwise an empty
    line, and none under oneline, which is log-tree's rule. A combined
    diff (``-c``, ``--cc``) is printed from its own path, which always
    writes the empty line, oneline included. Pinned against git 2.50.1.

    Args:
        commit (Commit): the commit whose diff follows.
        kind (str): the pretty format's kind.
        flags (DiffFlags): the diff flags.
    """
    if len(commit.parents) > 1 and flags.merge in ("combined",
                                                   "dense-combined"):
        return ""
    if kind == "oneline":
        return None
    return "---" if flags.stat and flags.patch else ""


def join_output(commit: Commit,
                header: bytes,
                bodies: list[bytes],
                kind: str,
                width: int,
                flags: DiffFlags,
                empty_summary: bool = False) -> bytes:
    if not bodies:
        return header
    line = separator_line(commit, kind, flags)
    blocks = []
    for index, body in enumerate(bodies):
        head = header
        if len(bodies) > 1 and kind not in ("format", "tformat"):
            parent = commit.parents[index].decode()
            full = commit.id.decode()
            if kind == "oneline":
                full, parent = full[:width], parent[:width]
            head = head.replace(full.encode(),
                                f"{full} (from {parent})".encode(), 1)
        gap = (f"{line}\n".encode()
               if head and body and line is not None else b"")
        if not body and head and empty_summary:
            gap = b"\n"
        blocks.append(head + gap + body)
    separator = b"\n" if kind not in ("format", "tformat", "oneline") else b""
    return separator.join(blocks)
