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

import { describe, expect, it } from 'vitest'
import { ISSUE_QUERY, TEAM_ISSUES_QUERY } from './queries.ts'

function selection(query: string, opener: string): string[] {
  const start = query.indexOf(opener) + opener.length
  let depth = 1
  for (let i = start; i < query.length; i++) {
    if (query[i] === '{') depth++
    if (query[i] === '}') depth--
    if (depth === 0) return query.slice(start, i).split(/\s+/).filter(Boolean)
  }
  throw new Error(`${opener} is never closed`)
}

describe('linear queries', () => {
  it('the listing and the read select the same issue fields', () => {
    const listed = selection(TEAM_ISSUES_QUERY, 'nodes {')
    expect(listed).toContain('identifier')
    expect(listed).toEqual(selection(ISSUE_QUERY, 'issue(id: $issueId) {'))
  })
})
