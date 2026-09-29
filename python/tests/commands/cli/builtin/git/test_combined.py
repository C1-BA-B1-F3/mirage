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

from mirage.commands.cli.builtin.git.combined import combined_lines


def _numbers(count: int, **edits: str) -> list[str]:
    return [edits.get(f'n{i}', str(i)) + '\n' for i in range(1, count + 1)]


def test_result_matching_every_parent_has_no_hunk():
    lines = _numbers(5)
    assert combined_lines([lines, lines], lines, dense=True) == []


def test_conflict_resolution_marks_each_parent_column():
    ours = ['a\n', 'MAIN\n', 'c\n']
    theirs = ['a\n', 'SIDE\n', 'c\n']
    result = ['a\n', 'BOTH\n', 'c\n']
    assert combined_lines([ours, theirs], result, dense=True) == [
        '@@@ -1,3 -1,3 +1,3 @@@\n', '  a\n', '- MAIN\n', ' -SIDE\n',
        '++BOTH\n', '  c\n'
    ]


def test_dense_drops_a_clean_merge_of_distant_edits():
    ours = _numbers(20, n8='eight')
    theirs = _numbers(20, n2='two')
    result = _numbers(20, n2='two', n8='eight')
    assert combined_lines([ours, theirs], result, dense=True) == []
    assert combined_lines([ours, theirs], result,
                          dense=False)[0] == ('@@@ -1,11 -1,11 +1,11 @@@\n')


def test_dense_keeps_edits_from_both_sides_within_context():
    ours = _numbers(20, n5='five')
    theirs = _numbers(20, n2='two')
    result = _numbers(20, n2='two', n5='five')
    assert combined_lines([ours, theirs], result, dense=True) == [
        '@@@ -1,8 -1,8 +1,8 @@@\n', '  1\n', '- 2\n', '+ two\n', '  3\n',
        '  4\n', ' -5\n', ' +five\n', '  6\n', '  7\n', '  8\n'
    ]


def test_empty_sides_number_from_one():
    assert combined_lines([[], []], ['new\n'], dense=True) == [
        '@@@ -1,0 -1,0 +1,1 @@@\n', '++new\n'
    ]
    assert combined_lines([['b\n'], ['b\n']], [],
                          dense=True) == ['@@@ -1,1 -1,1 +1,0 @@@\n', '--b\n']


def test_hunk_header_carries_function_context_less_its_last_byte():
    lines = [f'  body {i}\n' for i in range(1, 21)]
    lines[4] = 'function handleRequest(request, response) {\n'
    ours, theirs, result = list(lines), list(lines), list(lines)
    ours[14], theirs[14], result[14] = '  MAIN\n', '  SIDE\n', '  BOTH\n'
    body = combined_lines([ours, theirs], result, dense=True)
    assert body[0] == ('@@@ -12,7 -12,7 +12,7 @@@ '
                       'function handleRequest(request, respons\n')


def test_missing_final_newline_gets_no_marker():
    body = combined_lines([['x\n', 'MAIN'], ['x\n', 'SIDE']], ['x\n', 'BOTH'],
                          dense=True)
    assert body[-3:] == ['- MAIN\n', ' -SIDE\n', '++BOTH\n']


def test_zero_context_deletion_keeps_a_valid_empty_result_range():
    assert combined_lines(
        [['gone\n'], ['gone\n']], [], dense=True,
        context=0) == ['@@@ -1,1 -1,1 +1,0 @@@\n', '--gone\n']
