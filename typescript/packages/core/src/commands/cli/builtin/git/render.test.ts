// ========= Copyright 2026 @ Strukto.AI All Rights Reserved. =========
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.
// ========= Copyright 2026 @ Strukto.AI All Rights Reserved. =========

import { expect, it } from 'vitest'
import { branchLine, trackingLines } from './render.ts'

it.each([
  [0, 0, false, ["Your branch is up to date with 'origin/main'."]],
  [
    1,
    0,
    false,
    [
      "Your branch is ahead of 'origin/main' by 1 commit.",
      '  (use "git push" to publish your local commits)',
    ],
  ],
  [
    0,
    2,
    false,
    [
      "Your branch is behind 'origin/main' by 2 commits, and can be fast-forwarded.",
      '  (use "git pull" to update your local branch)',
    ],
  ],
  [
    1,
    1,
    false,
    [
      "Your branch and 'origin/main' have diverged,",
      'and have 1 and 1 different commits each, respectively.',
      '  (use "git pull" if you want to integrate the remote branch with yours)',
    ],
  ],
  [
    0,
    0,
    true,
    [
      "Your branch is based on 'origin/main', but the upstream is gone.",
      '  (use "git branch --unset-upstream" to fixup)',
    ],
  ],
])('words ahead %i, behind %i, gone %s as git does', (ahead, behind, gone, expected) => {
  expect(trackingLines({ label: 'origin/main', ahead, behind, gone })).toEqual(expected)
})

it.each([
  [{ label: 'origin/main', ahead: 0, behind: 0, gone: false }, '## main...origin/main'],
  [
    { label: 'origin/main', ahead: 1, behind: 2, gone: false },
    '## main...origin/main [ahead 1, behind 2]',
  ],
  [{ label: 'origin/gone', ahead: 0, behind: 0, gone: true }, '## main...origin/gone [gone]'],
])('names the upstream on the branch line', (upstream, expected) => {
  expect(branchLine('main', false, upstream)).toBe(expected)
})
