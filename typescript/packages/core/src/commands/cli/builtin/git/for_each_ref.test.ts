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
import { refSelected } from './for_each_ref.ts'

it.each([
  [[], true],
  [['refs/heads/feat/git'], true],
  [['refs/heads'], true],
  [['refs/heads/'], true],
  [['refs/hea'], false],
  [['refs/*'], false],
  [['refs/*/*'], false],
  [['refs/*/*/*'], true],
  [['refs/**'], true],
  [['**/git'], true],
  [['refs/heads/feat/g?t'], true],
  [['refs/tags', 'refs/heads/*/git'], true],
])('selects by prefix or path glob with %j', (patterns, expected) => {
  expect(refSelected('refs/heads/feat/git', patterns)).toBe(expected)
})
