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
import { commitFiles, pathsOf } from './wire.ts'
import { resolveRef } from './store.ts'
import type { RepoRow } from './store.ts'
import { authedRoute, everywhere, fail, param, route, withRepo } from './http.ts'

// Files changed between two refs. The fake diffs nothing, so a comparison is
// answered from the commits the head holds past the merge base, which is
// enough for "which files did the agent touch" and is what the graders ask.
// Either side is any ref `resolveRef` reads: a branch, or a commit by its full
// or abbreviated sha. A spec with no `...` compares nothing against the
// default branch, so every commit on it counts.
async function compare(ctx: Ctx<C>, repo: RepoRow): Promise<Reply> {
  const spec = param(ctx, 'basehead')
  const cut = spec.indexOf('...')
  const baseRef = cut < 0 ? '' : spec.slice(0, cut)
  const head = await resolveRef(ctx.db, ctx.tenant, repo, cut < 0 ? '' : spec.slice(cut + 3))
  const base =
    baseRef === '' ? { history: [] } : await resolveRef(ctx.db, ctx.tenant, repo, baseRef)
  if (head === null || base === null) return fail(404, 'Not Found')
  // The merge base is the newest commit both first-parent chains hold. A base
  // sharing none with the head is an error, not an empty diff: answering
  // "nothing changed" about an unrelated commit is the shape of wrongness that
  // reads as success.
  const onBase = new Set(base.history.map((c) => c.sha))
  const ahead =
    baseRef === '' ? head.history.length : head.history.findIndex((c) => onBase.has(c.sha))
  if (ahead < 0) return fail(404, 'No common ancestor between the two commits')
  const mergeBase = head.history[ahead]?.sha
  const behind = mergeBase === undefined ? 0 : base.history.findIndex((c) => c.sha === mergeBase)
  const touched = head.history.slice(0, ahead).flatMap(pathsOf)
  const files = commitFiles([...new Set(touched)], 'modified')
  const status =
    ahead === 0 ? (behind === 0 ? 'identical' : 'behind') : behind === 0 ? 'ahead' : 'diverged'
  return {
    status: 200,
    body: { status, ahead_by: ahead, behind_by: behind, files, commits: [] },
  }
}

export function compareRoutes(): KitRoute<C>[] {
  return everywhere<C>(API_PREFIXES, (p) => [
    route<C>('GET', `${p}/repos/:owner/:repo/compare/:basehead`, authedRoute(withRepo(compare))),
  ])
}
