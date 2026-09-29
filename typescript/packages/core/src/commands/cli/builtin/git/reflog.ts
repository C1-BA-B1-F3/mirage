import { IOResult } from '../../../../io/types.ts'
import type { CommandFnResult } from '../../../config.ts'
import { FlagView } from '../../../spec/flag_view.ts'
import type { CLIInvocation } from '../../types.ts'
import { GitError } from './errors.ts'
import { resolveCommit } from './revparse.ts'
import { loadRefs } from './refs.ts'
import { opened } from './repo.ts'
import { fatal } from './util.ts'
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

import { readOptional, under, writeFile } from './io.ts'
import type { Dispatch } from './types.ts'

const LOGS_DIR = 'logs'
const HEAD_LOG = 'logs/HEAD'
const ZERO = '0'.repeat(40)

const ENC = new TextEncoder()

/**
 * One reflog line, in git's own format.
 *
 * `<old> <new> <identity> <epoch> <offset>\t<message>`, with the old id all
 * zeroes when there was nothing there before. The tab is load-bearing: it is
 * what separates the fixed fields from a message that may itself contain spaces.
 *
 * @param before the id the ref held, zeroes when it held none
 * @param after the id it now holds
 * @param who the identity, `Name <email>`
 * @param when epoch seconds
 * @param message what happened, e.g. `commit: add delta`
 */
function entry(
  before: string,
  after: string,
  who: string,
  when: number,
  message: string,
): Uint8Array {
  return ENC.encode(`${before} ${after} ${who} ${String(when)} +0000\t${message}\n`)
}

/**
 * Add one line to a reflog, creating it if it is not there.
 *
 * Read-modify-write rather than an append op, because not every backend offers
 * one and a reflog is small. Losing the history here would only cost the `@{n}`
 * syntax, but `git branch` reads it to say where a detached HEAD detached from,
 * so an absent log makes a perfectly good checkout read as `(no branch)`.
 */
async function append(
  dispatch: Dispatch,
  gitdir: string,
  path: string,
  line: Uint8Array,
): Promise<void> {
  const target = under(gitdir, path)
  const existing = (await readOptional(dispatch, target)) ?? new Uint8Array(0)
  const merged = new Uint8Array(existing.length + line.length)
  merged.set(existing)
  merged.set(line, existing.length)
  await writeFile(dispatch, target, merged)
}

/**
 * Record one move of HEAD, and of the branch it is on.
 *
 * git writes both logs on every update: `logs/HEAD` always, and the branch's own
 * log when HEAD is attached to one. Both carry the same line. HEAD's log belongs
 * to the checkout and a branch's to the repository, so a linked worktree splits
 * them the way git does.
 *
 * @param dispatch workspace op dispatcher
 * @param gitdir this checkout's git directory, which owns HEAD's log
 * @param commondir the shared git directory, which owns the branches' logs
 * @param ref the branch ref that also moved, null when HEAD is detached
 * @param before the id HEAD held, null when it held none
 * @param after the id it now holds
 * @param who the identity to record
 * @param when epoch seconds
 * @param message what happened
 */
export async function record(
  dispatch: Dispatch,
  gitdir: string,
  commondir: string,
  ref: string | null,
  before: string | null,
  after: string,
  who: string,
  when: number,
  message: string,
): Promise<void> {
  const line = entry(before ?? ZERO, after, who, when, message)
  await append(dispatch, gitdir, HEAD_LOG, line)
  if (ref !== null) await append(dispatch, commondir, `${LOGS_DIR}/${ref}`, line)
}

export async function reflog(inv: CLIInvocation): Promise<CommandFnResult> {
  const fl = new FlagView(inv.flags)
  try {
    const repo = await opened(fl, inv.doors ?? {})
    const texts = inv.texts[0] === 'show' ? inv.texts.slice(1) : inv.texts
    const revision = texts[0] ?? 'HEAD'
    await resolveCommit(repo, revision)
    const refs = await loadRefs(repo.dispatch, repo.location.gitdir, repo.location.commondir)
    const ref =
      [
        revision,
        'refs/' + revision,
        'refs/heads/' + revision,
        'refs/tags/' + revision,
        'refs/remotes/' + revision,
      ].find((name) => refs.has(name)) ?? revision
    const root = ref === 'HEAD' ? repo.location.gitdir : repo.location.commondir
    const data = await readOptional(repo.dispatch, `${root}/logs/${ref}`)
    let rows = new TextDecoder()
      .decode(data ?? new Uint8Array())
      .split('\n')
      .filter(Boolean)
      .reverse()
    const limit = fl.asInt('max_count')
    if (limit !== undefined && limit >= 0) rows = rows.slice(0, limit)
    const name = ref.replace(/^refs\/(heads|remotes)\//, '')
    const out = rows
      .map((row, index) => {
        const tab = row.indexOf('\t')
        const oid = row.slice(0, tab).split(' ')[1] ?? ''
        return `${oid.slice(0, repo.abbrev)} ${name}@{${String(index)}}: ${row.slice(tab + 1)}\n`
      })
      .join('')
    return [new TextEncoder().encode(out), new IOResult()]
  } catch (err) {
    if (err instanceof GitError) return fatal(err)
    throw err
  }
}
