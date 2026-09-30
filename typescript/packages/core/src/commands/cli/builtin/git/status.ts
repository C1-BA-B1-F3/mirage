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

import { IOResult } from '../../../../io/types.ts'
import type { LinkView, StatPath } from '../../../../ops/types.ts'
import type { CommandFnResult } from '../../../config.ts'
import { FlagView } from '../../../spec/flag_view.ts'
import type { CLIInvocation } from '../../types.ts'
import git from 'isomorphic-git'
import { branchUpstream } from './branch.ts'
import { collect } from './changes.ts'
import { DWIM_RULES } from './constants.ts'
import { GitError, NoWorkspaceError } from './errors.ts'
import { short } from './format.ts'
import { readOptional, under } from './io.ts'
import { loadRefs, readHead } from './refs.ts'
import {
  branchLine,
  DETACHED_AT,
  DETACHED_FROM,
  longFormat,
  NO_BRANCH,
  relativeEntries,
  shortFormat,
} from './render.ts'
import { configBool, objectType, opened, repoArgs, type Repo } from './repo.ts'
import type { Dispatch, HeadRef, StatusEntry } from './types.ts'
import { fatal, startPoint } from './util.ts'
import { repoRelative } from './pathspec.ts'
import { UNTRACKED_ALL, UNTRACKED_NO, UNTRACKED_NORMAL } from './worktree.ts'
import { encodeText } from '../../../../shell/bytes.ts'

/** The parsed shape of a `git status` invocation. */
interface StatusFlags {
  /** `--porcelain`, the stable machine format. */
  readonly porcelain: boolean
  /** `-s`, the same rows meant for a person. */
  readonly short: boolean
  /** `-b`, prepend the `##` branch line. */
  readonly branch: boolean
  /** `-u`, which untracked files to report. */
  readonly untracked: string
  readonly ignored: boolean
}

/**
 * Read the raw status flag kwargs into a frozen struct.
 *
 * `-u` carries its mode attached or not at all, and a bare one means `all`,
 * which is why the value is read as a string first and only then as a boolean.
 */
function parseFlags(fl: FlagView): StatusFlags {
  const stated = fl.asStr('untracked_files')
  const mode = stated ?? (fl.asBool('untracked_files') ? UNTRACKED_ALL : UNTRACKED_NORMAL)
  const version = fl.asStr('porcelain')
  if (version != null && !['1', 'v1'].includes(version))
    throw new GitError(`unsupported porcelain version '${version}'`)
  return {
    porcelain: fl.asBool('porcelain') || fl.asStr('porcelain') != null,
    short: fl.asBool('short'),
    branch: fl.asBool('branch'),
    ignored: fl.asBool('ignored'),
    untracked: mode,
  }
}

/**
 * Status rows as a person reads them, relative to where git runs.
 *
 * git's human formats name paths from the invocation directory unless
 * `status.relativePaths` is false; porcelain never does. From outside the work
 * tree they stay relative to its root.
 */
async function displayed(repo: Repo, start: string, rows: StatusEntry[]): Promise<StatusEntry[]> {
  if (!(await configBool(repo, 'status.relativePaths', true))) return rows
  return relativeEntries(rows, repoRelative(repo.location, start, '.'))
}

const CHECKOUT_MOVE = 'checkout: moving from '

/**
 * How the status names where a detached HEAD came from: the checkout's target
 * when it still names exactly one ref holding that commit (a tag or
 * remote-tracking branch by its short name), the abbreviated id otherwise.
 */
async function detachedLabel(repo: Repo, target: string, moved: string): Promise<string> {
  const refs = await loadRefs(repo.dispatch, repo.location.gitdir, repo.location.commondir)
  const found = [...new Set(DWIM_RULES.map((rule) => rule.replace('{}', target)))].filter((name) =>
    refs.has(name),
  )
  const [only] = found
  if (target !== 'HEAD' && found.length === 1 && only !== undefined) {
    let oid = await git.resolveRef({ ...repoArgs(repo), ref: only })
    while ((await objectType(repo, oid)) === 'tag')
      oid = (await git.readTag({ ...repoArgs(repo), oid })).tag.object
    if (oid === moved) return only.replace(/^refs\/tags\//, '').replace(/^refs\/remotes\//, '')
  }
  return short(moved, repo.abbrev)
}

/**
 * The first line of a status on a detached HEAD, read off the reflog.
 *
 * git names the target of the newest `checkout: moving from` entry, `at` while
 * HEAD is still there and `from` once it has moved on, and says it is on no
 * branch when no checkout put it there, which is what a clone of a tag or of a
 * detached HEAD reads (pinned against git 2.47.3 and 2.50.1).
 */
async function detachedLine(repo: Repo, head: HeadRef): Promise<string> {
  const log = await readOptional(repo.dispatch, under(repo.location.gitdir, 'logs/HEAD'))
  const rows = new TextDecoder()
    .decode(log ?? new Uint8Array())
    .split('\n')
    .filter(Boolean)
  for (const row of rows.reverse()) {
    const tab = row.indexOf('\t')
    const message = row.slice(tab + 1)
    if (!message.startsWith(CHECKOUT_MOVE)) continue
    const to = message.indexOf(' to ', CHECKOUT_MOVE.length)
    if (to < 0) continue
    const target = message.slice(to + 4)
    const moved = row.slice(0, tab).split(' ')[1] ?? ''
    const label = await detachedLabel(repo, target, moved)
    return `${head.commit === moved ? DETACHED_AT : DETACHED_FROM}${label}`
  }
  return NO_BRANCH
}

/**
 * The default status report, as a string.
 *
 * Split out so `commit` can print it when it has nothing to commit: git shows
 * the whole status there rather than a one-line refusal, and two renderings of
 * the same thing would drift. Its paths are relative to `start`, where git runs.
 */
export async function renderReport(
  repo: Repo,
  dispatch: Dispatch,
  statPath: StatPath,
  head: HeadRef,
  start: string,
  links: LinkView | null = null,
): Promise<string> {
  const [rows, state, noCommits] = await collect(repo, dispatch, statPath, UNTRACKED_NORMAL, links)
  const fully = await configBool(repo, 'core.quotepath', true)
  const detached = head.branch !== null ? '' : await detachedLine(repo, head)
  return longFormat(
    await displayed(repo, start, rows),
    head.branch,
    detached,
    noCommits,
    state.merging,
    false,
    fully,
    await branchUpstream(repo, head, noCommits),
  )
}

/**
 * Show the working tree status.
 *
 * Three sources, compared pairwise: HEAD's tree against the index says what a
 * commit would record, and the index against the working tree says what it would
 * leave behind. Everything the report prints is one of those two answers, or a
 * path neither side knows about.
 */
export async function status(inv: CLIInvocation): Promise<CommandFnResult> {
  const doors = inv.doors ?? {}
  const fl = new FlagView(inv.flags)
  try {
    const dispatch = doors.dispatch
    const statPath = doors.statPath
    if (statPath === undefined || dispatch === undefined) {
      throw new NoWorkspaceError()
    }
    const parsed = parseFlags(fl)
    const repo = await opened(fl, doors, true)
    const head = await readHead(dispatch, repo.location.gitdir)
    const [rows, state, noCommits] = await collect(
      repo,
      dispatch,
      statPath,
      parsed.untracked,
      doors.ns?.links ?? null,
      parsed.ignored,
    )
    const fully = await configBool(repo, 'core.quotepath', true)
    const shown = parsed.porcelain ? rows : await displayed(repo, startPoint(fl), rows)
    const upstream = await branchUpstream(repo, head, noCommits)
    const detached = head.branch !== null ? '' : await detachedLine(repo, head)
    const body =
      parsed.porcelain || parsed.short
        ? shortFormat(
            shown,
            parsed.branch ? branchLine(head.branch, noCommits, upstream) : null,
            fully,
          )
        : longFormat(
            shown,
            head.branch,
            detached,
            noCommits,
            state.merging,
            parsed.untracked === UNTRACKED_NO,
            fully,
            upstream,
          )
    return [encodeText(body), new IOResult()]
  } catch (err) {
    if (err instanceof GitError) return fatal(err)
    throw err
  }
}
