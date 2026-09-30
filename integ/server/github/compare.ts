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

import type { Ctx, KitRoute, Reply } from '../kit/typescript/index.ts'
import { API_PREFIXES } from './config.ts'
import type { C } from './config.ts'
import { changeJson, diffTrees } from './diff.ts'
import type { FileChange } from './diff.ts'
import type { CommitRow } from './wire.ts'
import { commitTree, commitsJson, divergence, forkOwnedBy, resolveRef, treeAt } from './store.ts'
import type { RepoRow, Resolved } from './store.ts'
import { authedRoute, diffReply, everywhere, fail, param, route, withRepo } from './http.ts'

/**
 * What a head holds past a base: its commits past the merge base, newest
 * first, how many the base holds past it, and every path the head's tree
 * changed against the merge base's, with the commit either side. A null base
 * compares the head against nothing, so every commit and file it has counts.
 * The head may live in another repository of the network, a fork.
 */
export interface Range {
  ahead: CommitRow[]
  behind: number
  before: string
  after: string
  changes: FileChange[]
}

// Null when the two share no commit: a base the head never came from is no
// base, and answering "nothing changed" about it is the shape of wrongness
// that reads as success.
export async function rangeOf(
  db: C,
  tenant: string,
  repo: RepoRow,
  base: Resolved | null,
  head: Resolved,
  headRepo: RepoRow = repo,
): Promise<Range | null> {
  const met =
    base === null
      ? { ahead: head.history, behind: 0, mergeBase: null }
      : divergence(head.history, base.history)
  if (met === null) return null
  const before =
    met.mergeBase === null ? new Map() : await commitTree(db, tenant, repo, met.mergeBase)
  const after = (await treeAt(db, tenant, headRepo, head)) ?? new Map()
  return {
    ahead: met.ahead,
    behind: met.behind,
    before: met.mergeBase?.sha ?? '',
    after: head.history[0]?.sha ?? '',
    changes: diffTrees(before, after),
  }
}

// What one commit changed: its tree against its first parent's, or against
// nothing for a root. `history` is newest first from the commit, as
// `resolveRef` answers it.
export async function commitChanges(
  db: C,
  tenant: string,
  repo: RepoRow,
  history: CommitRow[],
): Promise<FileChange[]> {
  const [commit, parent] = history
  if (commit === undefined) return []
  const before = parent === undefined ? new Map() : await commitTree(db, tenant, repo, parent)
  return diffTrees(before, await commitTree(db, tenant, repo, commit))
}

// Either side is any ref `resolveRef` reads: a branch, a tag, or a commit by
// its full or abbreviated sha, and the head may be `owner:ref` in a fork of
// the network, as GitHub reads `base...owner:head`. A spec with no `...` compares nothing against the
// default branch, so every commit on it counts. Asked for as a diff, the body
// is the unified diff of the same range.
async function compare(ctx: Ctx<C>, repo: RepoRow): Promise<Reply> {
  const spec = param(ctx, 'basehead')
  const cut = spec.indexOf('...')
  const baseRef = cut < 0 ? '' : spec.slice(0, cut)
  const headSpec = cut < 0 ? '' : spec.slice(cut + 3)
  const colon = headSpec.indexOf(':')
  const headRef = colon < 0 ? headSpec : headSpec.slice(colon + 1)
  const home =
    colon < 0
      ? repo
      : await forkOwnedBy(ctx.db, ctx.tenant, repo, headSpec.slice(0, colon), headRef)
  const head = home === null ? null : await resolveRef(ctx.db, ctx.tenant, home, headRef)
  const base = baseRef === '' ? null : await resolveRef(ctx.db, ctx.tenant, repo, baseRef)
  if (home === null || head === null || (baseRef !== '' && base === null)) {
    return fail(404, 'Not Found')
  }
  const range = await rangeOf(ctx.db, ctx.tenant, repo, base, head, home)
  if (range === null) return fail(404, 'No common ancestor between the two commits')
  const diff = diffReply(ctx, range.changes)
  if (diff !== null) return diff
  const ahead = range.ahead.length
  const status =
    ahead === 0
      ? range.behind === 0
        ? 'identical'
        : 'behind'
      : range.behind === 0
        ? 'ahead'
        : 'diverged'
  return {
    status: 200,
    body: {
      status,
      ahead_by: ahead,
      behind_by: range.behind,
      total_commits: ahead,
      commits: await commitsJson(ctx.db, ctx.tenant, home, [...range.ahead].reverse()),
      files: range.changes.map((c) => changeJson(repo.fullName, c, range.before, range.after)),
    },
  }
}

export function compareRoutes(): KitRoute<C>[] {
  return everywhere<C>(API_PREFIXES, (p) => [
    route<C>('GET', `${p}/repos/:owner/:repo/compare/:basehead`, authedRoute(withRepo(compare))),
  ])
}
