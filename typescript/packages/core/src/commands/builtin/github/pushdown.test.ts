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

// Mirror of python/tests/commands/builtin/github/test_narrow.py. The Python
// suite drives grep/rg end-to-end against a mock GitHub API; here we test the
// shared pieces directly: narrowScope (code-search push-down on subdirs and
// regex-extracted literals, gated on -w).

import { describe, expect, it } from 'vitest'
import { GitHubAccessor } from '../../../accessor/github.ts'
import type { GitHubTransport } from '../../../core/github/client.ts'
import type { TreeEntry } from '../../../core/github/tree_entry.ts'
import { PathSpec } from '../../../types.ts'
import { narrowScope, scopeRefusal } from './pushdown.ts'

// 150 blobs under src/ so the scope clears SCOPE_WARN (100) and search kicks in.
function bigTree(): Record<string, TreeEntry> {
  const tree: Record<string, TreeEntry> = {
    src: { path: 'src', type: 'tree', sha: 'd', size: null },
  }
  for (let i = 0; i < 150; i += 1) {
    const p = `src/f${String(i)}.py`
    tree[p] = { path: p, type: 'blob', sha: `s${String(i)}`, size: 10 }
  }
  return tree
}

interface SearchCall {
  q: string
}

interface Answer {
  fullName?: string
  total?: number
  tree?: Record<string, TreeEntry>
  truncated?: boolean
}

function makeAccessor(
  searchHits: string[],
  calls: SearchCall[],
  answer: Answer = {},
): GitHubAccessor {
  const fullName = answer.fullName ?? 'o/r'
  const transport: GitHubTransport = {
    get(path: string, params?: Record<string, string>): Promise<unknown> {
      if (path === '/search/code') {
        calls.push({ q: params?.q ?? '' })
        return Promise.resolve({
          total_count: answer.total ?? searchHits.length,
          incomplete_results: false,
          items: searchHits.map((p) => ({
            path: p,
            sha: 'x',
            repository: { full_name: fullName },
          })),
        })
      }
      throw new Error(`unexpected transport call: ${path}`)
    },
    request(method: string, path: string): Promise<unknown> {
      throw new Error(`unexpected transport call: ${method} ${path}`)
    },
    requestWithResponse(method: string, path: string): Promise<never> {
      throw new Error(`unexpected transport call: ${method} ${path}`)
    },
  }
  return new GitHubAccessor({
    transport,
    owner: 'o',
    repo: 'r',
    ref: 'main',
    defaultBranch: 'main',
    tree: answer.tree ?? bigTree(),
    truncated: answer.truncated ?? false,
  })
}

function subdir(): PathSpec {
  return new PathSpec({
    virtual: '/src',
    directory: '/src',
    vfsPath: 'src',
    resolved: false,
  })
}

describe('narrowScope', () => {
  it('narrows a large recursive scope via code search on a literal', async () => {
    const calls: SearchCall[] = []
    const acc = makeAccessor(['src/f1.py', 'src/f2.py'], calls)
    const res = await narrowScope(acc, [subdir()], 'import', false, true, true)
    expect(res.usedSearch).toBe(true)
    expect(res.fileCount).toBe(2)
    expect(res.resolved.map((p) => p.virtual).sort()).toEqual(['/src/f1.py', '/src/f2.py'])
    expect(calls[0]?.q).toContain('import')
    expect(calls[0]?.q).toContain('path:src')
  })

  it('skips search for a regex even under -w', async () => {
    // A regex narrows on an extracted literal, so the searched term is only
    // part of the match: a whole-word search for `import` never returns a file
    // whose only token is `importos`.
    const calls: SearchCall[] = []
    const acc = makeAccessor(['src/f3.py'], calls)
    const res = await narrowScope(acc, [subdir()], 'import.*os', false, true, true)
    expect(res.usedSearch).toBe(false)
    expect(calls).toHaveLength(0)
  })

  it('does not search a non-recursive scope', async () => {
    const calls: SearchCall[] = []
    const acc = makeAccessor(['src/f1.py'], calls)
    const res = await narrowScope(acc, [subdir()], 'import', false, false, true)
    expect(res.usedSearch).toBe(false)
    expect(calls).toHaveLength(0)
  })

  it('does not search a regex with no provable literal', async () => {
    const calls: SearchCall[] = []
    const acc = makeAccessor(['src/f1.py'], calls)
    const res = await narrowScope(acc, [subdir()], 'foo|bar', false, true, true)
    expect(res.usedSearch).toBe(false)
    expect(calls).toHaveLength(0)
  })

  it('skips search without -w', async () => {
    // Code search matches whole words while grep matches substrings, so a
    // bare literal would narrow to a strict subset and silently drop files
    // that contain it only inside a longer word.
    const calls: SearchCall[] = []
    const acc = makeAccessor(['src/f1.py'], calls)
    const res = await narrowScope(acc, [subdir()], 'import', false, true, false)
    expect(res.usedSearch).toBe(false)
    expect(calls).toHaveLength(0)
  })
})

// Twins of the end-to-end tests in
// python/tests/commands/builtin/github/test_pushdown.py, at the narrowScope
// seam grep and rg share. A fallback resolves the scope itself, which the
// scan then walks, so it reads as the scope path and the whole file count.
describe('narrowScope trusts only a complete, own-repository answer', () => {
  it('falls back on a foreign answer', async () => {
    // A fork shares the path; trusted, it would narrow grep to one file.
    const calls: SearchCall[] = []
    const acc = makeAccessor(['src/f1.py'], calls, { fullName: 'o/r-fork' })
    const res = await narrowScope(acc, [subdir()], 'import', false, true, true)
    expect(res.usedSearch).toBe(false)
    expect(res.fileCount).toBe(150)
    expect(res.resolved.map((p) => p.virtual)).toEqual(['/src'])
  })

  it('falls back on a truncated answer', async () => {
    const calls: SearchCall[] = []
    const acc = makeAccessor(['src/f1.py'], calls, { total: 7 })
    const res = await narrowScope(acc, [subdir()], 'import', false, true, true)
    expect(res.usedSearch).toBe(false)
    expect(res.fileCount).toBe(150)
    expect(res.resolved.map((p) => p.virtual)).toEqual(['/src'])
  })

  it.each<[string, boolean]>([
    ['import path:src', true],
    ['foo NOT bar', false],
  ])('never searches %j', async (pattern, fixedString) => {
    // Without -F a colon pattern is not a literal and was never searched;
    // the -F spelling and the operator are what reached code search before.
    const calls: SearchCall[] = []
    const acc = makeAccessor(['src/f1.py'], calls)
    const res = await narrowScope(acc, [subdir()], pattern, fixedString, true, true)
    expect(res.usedSearch).toBe(false)
    expect(calls).toHaveLength(0)
  })

  it('still narrows on a complete own answer', async () => {
    const calls: SearchCall[] = []
    const acc = makeAccessor(['src/f1.py'], calls)
    const res = await narrowScope(acc, [subdir()], 'import', false, true, true)
    expect(res.usedSearch).toBe(true)
    expect(res.resolved.map((p) => p.virtual)).toEqual(['/src/f1.py'])
  })

  it('never trusts a narrowing over a truncated tree', async () => {
    // A truncated tree cannot list every file code search skips, so no
    // answer can be shown to be the whole set.
    const calls: SearchCall[] = []
    const acc = makeAccessor(['src/f1.py'], calls, { truncated: true })
    const res = await narrowScope(acc, [subdir()], 'import', false, true, true)
    expect(res.usedSearch).toBe(false)
    expect(calls).toHaveLength(0)
  })

  it('does not read a big binary file', async () => {
    // A recursive walk skips binary extensions, and an unindexed file joins
    // the narrowing only as a file that walk would have read.
    const tree = bigTree()
    tree['src/model.gguf'] = { path: 'src/model.gguf', type: 'blob', sha: 'g', size: 400_000 }
    const calls: SearchCall[] = []
    const acc = makeAccessor(['src/f1.py'], calls, { tree })
    const res = await narrowScope(acc, [subdir()], 'import', false, true, true)
    expect(res.usedSearch).toBe(true)
    expect(res.resolved.map((p) => p.virtual)).toEqual(['/src/f1.py'])
  })

  it('never narrows when an operand is a file', async () => {
    // A full scan reads every file named on the line, binary extension or
    // not, so a narrowing is only offered over directory operands.
    const calls: SearchCall[] = []
    const acc = makeAccessor(['src/f1.py'], calls)
    const named = new PathSpec({ virtual: '/src/f2.py', directory: '/src', vfsPath: 'src/f2.py' })
    const res = await narrowScope(acc, [subdir(), named], 'import', false, true, true)
    expect(res.usedSearch).toBe(false)
    expect(calls).toHaveLength(0)
  })

  it('narrows to nothing when the binary filter leaves nothing', async () => {
    // Every candidate is a binary a walk skips, so the scan the narrowing
    // stands in for reads nothing; grep and rg answer that as no match
    // rather than handing an empty operand list on, which would read
    // standard input.
    const tree = bigTree()
    tree['src/model.gguf'] = { path: 'src/model.gguf', type: 'blob', sha: 'g', size: 400_000 }
    const calls: SearchCall[] = []
    const acc = makeAccessor([], calls, { tree })
    const res = await narrowScope(acc, [subdir()], 'import', false, true, true)
    expect(res).toEqual({ resolved: [], fileCount: 0, usedSearch: true })
  })

  it('still reads a file code search never indexes', async () => {
    // src/f7.py sits over the 384 KB limit, so code search can never name it.
    const tree = bigTree()
    tree['src/f7.py'] = { path: 'src/f7.py', type: 'blob', sha: 's7', size: 400_000 }
    const calls: SearchCall[] = []
    const acc = makeAccessor(['src/f1.py'], calls, { tree })
    const res = await narrowScope(acc, [subdir()], 'import', false, true, true)
    expect(res.usedSearch).toBe(true)
    expect(res.resolved.map((p) => p.virtual)).toEqual(['/src/f1.py', '/src/f7.py'])
  })
})

// Twin of test_a_scope_too_large_to_scan_names_why_it_was_not_narrowed.
describe('scopeRefusal', () => {
  it.each<[string, boolean, string]>([
    [
      'grep',
      true,
      'grep: 12 files in scope and code search could not narrow them; narrow the path\n',
    ],
    ['grep', false, 'grep: 12 files in scope, narrow the path, or use -w to enable code search\n'],
    ['rg', true, 'rg: 12 files in scope and code search could not narrow them; narrow the path\n'],
  ])('words the %s refusal for -w=%s', (cmd, wholeWord, stderr) => {
    // With -w given, telling the caller to add -w is wrong: code search ran
    // and its answer could not be trusted.
    expect(scopeRefusal(cmd, 12, wholeWord)).toBe(stderr)
  })
})
