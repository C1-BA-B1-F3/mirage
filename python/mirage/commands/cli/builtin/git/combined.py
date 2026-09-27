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

from difflib import SequenceMatcher

from mirage.commands.cli.builtin.git.constants import FUNCNAME_START, GIT_SPACE

# Git 2.50.1 underflows the result count for -U0 combined deletions.
# Keep the valid zero-length range instead of its unsigned-size overflow.
CONTEXT = 3
COMMENT_BYTES = 40

Lost = list[list[tuple[str, int]]]


def combined_lines(parents: list[list[str]],
                   result: list[str],
                   dense: bool,
                   context: int = CONTEXT) -> list[str]:
    """The hunks of a combined diff, as git's combine-diff.c selects them.

    Row ``k`` is result line ``k``, carrying the parent lines deleted just
    before it; row ``len(result)`` carries the deletions at the end.
    ``added[k]`` has bit ``p`` set when parent ``p`` lacks result line
    ``k``, and each lost line records the parents that had it.

    Args:
        parents (list[list[str]]): each parent's lines, newlines kept.
        result (list[str]): the merge result's lines, newlines kept.
        dense (bool): ``--cc``, which drops a hunk whose every change
            comes from the same proper subset of the parents.
        context (int): the requested number of context lines.
    """
    size = len(result)
    added = [0] * (size + 1)
    lost: Lost = [[] for _ in range(size + 1)]
    for parent, old in enumerate(parents):
        bit = 1 << parent
        for tag, i, end, j, stop in SequenceMatcher(
                a=old, b=result, autojunk=False).get_opcodes():
            if tag == 'equal':
                continue
            for at in range(j, stop):
                added[at] |= bit
            bucket = lost[j]
            for line in old[i:end]:
                found = next((n for n, (text, owners) in enumerate(bucket)
                              if text == line and not owners & bit), None)
                if found is None:
                    bucket.append((line, bit))
                else:
                    bucket[found] = (line, bucket[found][1] | bit)
    marked = [bool(added[at] or lost[at]) for at in range(size + 1)]
    if dense:
        _drop_one_sided(added, lost, marked, (1 << len(parents)) - 1, context)
    hidden = _give_context(added, marked, context)
    return _dump(result, added, lost, marked, hidden, len(parents))


def _tail(added: list[int], begin: int, at: int) -> int:
    """Pull a hunk's end in by one when its last row only hangs deletions.

    Args:
        added (list[int]): per row, the parents lacking the result line.
        begin (int): the hunk's first row.
        at (int): the first row past the hunk.
    """
    return at - 1 if begin + 1 <= at and not added[at - 1] else at


def _find(marked: list[bool], at: int, want: bool) -> int:
    """The first row at or after ``at`` whose mark is ``want``.

    Args:
        marked (list[bool]): per row, whether it is shown.
        at (int): where to start looking.
        want (bool): the mark being looked for.
    """
    while at < len(marked) and marked[at] != want:
        at += 1
    return at


def _drop_one_sided(added: list[int], lost: Lost, marked: list[bool],
                    everyone: int, context: int) -> None:
    """Unmark each hunk that only some of the parents changed alike.

    Args:
        added (list[int]): per row, the parents lacking the result line.
        lost (Lost): per row, the deleted lines
            with the parents that had each.
        marked (list[bool]): per row, whether it is shown; updated.
        everyone (int): the mask holding every parent.
        context (int): the requested number of context lines.
    """
    size = len(marked) - 1
    at = 0
    while True:
        at = _find(marked, at, True)
        if at > size:
            return
        begin, end = at, at + 1
        while end <= size:
            if not marked[end]:
                reach = min(_tail(added, begin, end) + context, size + 1)
                ahead = next(
                    (k for k in range(reach - 1, end - 1, -1) if marked[k]),
                    None)
                if ahead is None:
                    break
                end = ahead
            end += 1
        sides = {added[k] for k in range(begin, end) if added[k]}
        sides.update(owners for k in range(begin, end)
                     for _, owners in lost[k])
        if len(sides) == 1 and everyone not in sides:
            for k in range(begin, end):
                marked[k] = False
        at = end


def _give_context(added: list[int], marked: list[bool],
                  context: int) -> set[int]:
    """Paint context rows around the marked ones, joining close hunks.

    Returns the rows painted as leading context that were not marked
    before, whose deleted lines git leaves out.

    Args:
        added (list[int]): per row, the parents lacking the result line.
        marked (list[bool]): per row, whether it is shown; updated.
    """
    size = len(marked) - 1
    hidden: set[int] = set()
    at = _find(marked, 0, True)
    while at <= size:
        for k in range(max(0, at - context), at):
            if not marked[k]:
                hidden.add(k)
            marked[k] = True
        while True:
            gap = _find(marked, at, False)
            if gap > size:
                return hidden
            ahead = _find(marked, gap, True)
            gap = _tail(added, at, gap)
            if ahead >= gap + context:
                break
            for k in range(gap, ahead):
                marked[k] = True
            at = ahead
        at = ahead
        for k in range(gap, min(gap + context, size + 1)):
            marked[k] = True
    return hidden


def _dump(result: list[str], added: list[int], lost: Lost, marked: list[bool],
          hidden: set[int], count: int) -> list[str]:
    """Render each run of marked rows as one ``@@@`` hunk.

    Args:
        result (list[str]): the merge result's lines.
        added (list[int]): per row, the parents lacking the result line.
        lost (Lost): per row, the deleted lines
            with the parents that had each.
        marked (list[bool]): per row, whether it is shown.
        hidden (set[int]): rows whose deleted lines are left out.
        count (int): how many parents the merge has.
    """
    size = len(result)
    starts = [[1] * count]
    for k in range(size + 1):
        row = list(starts[-1])
        for p in range(count):
            row[p] += sum(owners >> p & 1 for _, owners in lost[k])
            if k < size and not added[k] >> p & 1:
                row[p] += 1
        starts.append(row)
    marker = '@' * (count + 1)
    output: list[str] = []
    at = 0
    while True:
        comment = None
        while at <= size and not marked[at]:
            if at < size and result[at][:1] in FUNCNAME_START:
                comment = result[at]
            at += 1
        if at > size:
            return output
        end = _find(marked, at + 1, False)
        ranges = ' '.join(f'-{starts[at][p]},{starts[end][p] - starts[at][p]}'
                          for p in range(count))
        rows = end - at - int(end > size)
        output.append(f'{marker} {ranges} +{at + 1},{rows} {marker}'
                      f'{_funcname(comment)}\n')
        for k in range(at, end):
            if k not in hidden:
                output.extend(''.join('-' if owners >> p & 1 else ' '
                                      for p in range(count)) + _eol(text)
                              for text, owners in lost[k])
            if k < size:
                output.append(''.join('+' if added[k] >> p & 1 else ' '
                                      for p in range(count)) + _eol(result[k]))
        at = end


def _funcname(line: str | None) -> str:
    """The hunk header's trailing context, cut the way git cuts it.

    git keeps the first 40 bytes up to a newline, then stops BEFORE the
    last non-blank byte, so the context always loses its final byte.

    Args:
        line (str | None): the last line skipped before the hunk that
            starts with a letter, ``_`` or ``$``.
    """
    if line is None:
        return ''
    head = line.encode()[:COMMENT_BYTES].split(b'\n', 1)[0].split(b'\0', 1)[0]
    end = max((i for i, c in enumerate(head) if c not in GIT_SPACE), default=0)
    return ' ' + head[:end].decode(errors='replace') if end else ''


def _eol(line: str) -> str:
    """A line as printed: always newline-terminated, with no marker.

    Args:
        line (str): the line, with or without its newline.
    """
    return line if line.endswith('\n') else line + '\n'
