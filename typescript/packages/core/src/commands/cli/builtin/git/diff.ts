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

import git from 'isomorphic-git'
import { headEntries } from './changes.ts'
import { readIndex, refuseUnresolved } from './index_file.ts'
import { treeEntries, type TreeEntry } from './tree.ts'
import { compare, renderChanges } from './diff_output.ts'
import { HEAD } from './constants.ts'

import { IOResult } from '../../../../io/types.ts'
import type { CommandFnResult } from '../../../config.ts'
import { FlagView } from '../../../spec/flag_view.ts'
import type { CLIInvocation } from '../../types.ts'
import { GitError, InvalidOptionError, NoMergeBaseError } from './errors.ts'
import { treeOutput, parseDiffFlags, renamesEnabled } from './diff_output.ts'
import { configBool, repoArgs, type Repo } from './repo.ts'
import { opened } from './session.ts'
import { mergeBases, rangeCommits, resolveCommit } from './revparse.ts'
import { checkOperands, escaped, fatal } from './util.ts'
import { encodeText } from '../../../../shell/bytes.ts'

const ENC = new TextEncoder()

/** The tree one revision names. */
async function treeOf(repo: Repo, revision: string): Promise<string> {
  const oid = await resolveCommit(repo, revision)
  return (await git.readCommit({ ...repoArgs(repo), oid })).commit.tree
}

/**
 * The two trees a diff compares, and any warning.
 *
 * One revision is compared with HEAD and two with each other. `A..B` is the
 * two-revision form written as one operand, and `A...B` compares B with the
 * merge base of the two, which is what a branch changed since it forked; with
 * several bases git warns and takes the first (pinned against git 2.50).
 */
async function sides(repo: Repo, texts: readonly string[]): Promise<[string, string, string]> {
  const first = texts[0] ?? HEAD
  const ends = texts.length === 1 ? await rangeCommits(repo, first) : null
  if (ends === null) return [await treeOf(repo, first), await treeOf(repo, texts[1] ?? HEAD), '']
  const [left, right, symmetric] = ends
  if (!symmetric) return [left.tree, right.tree, '']
  const bases = await mergeBases(repo, left, right)
  const base = bases[0]
  if (base === undefined) throw new NoMergeBaseError(first)
  const warning =
    bases.length > 1 ? `warning: ${first}: multiple merge bases, using ${base.oid}\n` : ''
  return [base.tree, right.tree, warning]
}

/**
 * Diff commits or compare staged content with a commit.
 *
 * One revision diffs it against HEAD's tree, two diff against each other. The
 * index is compared with the named revision under --cached or --staged,
 * defaulting to HEAD or the empty tree on an unborn branch.
 */
export async function diff(inv: CLIInvocation): Promise<CommandFnResult> {
  const doors = inv.doors ?? {}
  const texts = [...inv.texts]
  const fl = new FlagView(inv.flags)
  const cached = fl.asBool('cached') || fl.asBool('staged')
  if (texts.length === 0 && !cached) return [null, new IOResult()]
  try {
    checkOperands(texts, InvalidOptionError, escaped(inv.argv))
    const repo = await opened(fl, doors)
    const flags = parseDiffFlags(
      fl,
      true,
      'off',
      true,
      await renamesEnabled(repo),
      await configBool(repo, 'core.quotepath', true),
    )
    let body: string,
      warning = ''
    if (cached) {
      if (texts.length > 1) throw new GitError('--cached accepts at most one revision')
      const state = await readIndex(repo, repo.dispatch)
      refuseUnresolved(state)
      const before = texts.length
        ? await treeEntries(repo, await treeOf(repo, texts[0] ?? HEAD))
        : ((await headEntries(repo)) ?? new Map<string, TreeEntry>())
      const after = new Map(
        [...state.entries].map(([path, entry]) => [
          path,
          { oid: entry.oid, mode: entry.mode.toString(8).padStart(6, '0') },
        ]),
      )
      body = await renderChanges(repo, await compare(repo, before, after, flags.renames), flags)
    } else {
      const [before, after, note] = await sides(repo, texts)
      warning = note
      body = await treeOutput(repo, before, after, flags)
    }
    const result = warning ? new IOResult({ stderr: ENC.encode(warning) }) : new IOResult()
    if (body === '') return [null, result]
    return [encodeText(body), result]
  } catch (err) {
    if (err instanceof GitError) return fatal(err)
    throw err
  }
}
