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
import { BreError, searchBre } from '../../../builtin/utils/bre.ts'
import { GitError } from './errors.ts'
import { HEAD } from './constants.ts'

import type { FlagView } from '../../../spec/flag_view.ts'
import { isoTimestamp } from '../../../../utils/dates.ts'
import { BadDateError, IncompatibleLogOptionsError, UnrecognizedArgumentError } from './errors.ts'
import { MEDIUM, parsePretty, type CommitFacts, type LogFormat } from './format.ts'
import { touches } from './pickaxe.ts'
import { loadRefs, SYMREF_PREFIX } from './refs.ts'
import { commitFacts, repoArgs, type Repo } from './repo.ts'
import { compareCodePoints } from '../../../../utils/sort.ts'

const BRANCH_PREFIX = 'refs/heads/'
// How many hidden commits a limited walk takes past the point where only
// hidden ones are queued, git's SLOP.
const SLOP = 5
const TAG_PREFIX = 'refs/tags/'
const REMOTE_PREFIX = 'refs/remotes/'

/** The parsed shape of a `git log` invocation. */
export interface LogFlags {
  readonly authors: readonly RegExp[]
  readonly minParents: number | null
  readonly maxParents: number | null
  readonly firstParent: boolean
  readonly date: string
  readonly decorate: boolean
  /** `-n`, how many commits to print. */
  readonly maxCount: number | null
  /** `--oneline`, one abbreviated row per commit. */
  readonly oneline: boolean
  /** `--reverse`, oldest first. */
  readonly reverse: boolean
  /** `-S`, the pickaxe string. */
  readonly search: string | null
  /** `--since` as an epoch second. */
  readonly since: number | null
  /** `--until` as an epoch second. */
  readonly until: number | null
  /** `--all`, start from every ref as well. */
  readonly allRefs: boolean
  /**
   * How each commit renders; medium unless `--oneline` or
   * `--pretty`/`--format` said otherwise.
   */
  readonly pretty: LogFormat
  /**
   * Print abbreviated ids, which `--oneline` implies and
   * `--pretty=oneline` alone does not.
   */
  readonly abbrevCommit: boolean
  /** `--graph`, draw the history beside the commits. */
  readonly graph: boolean
  /**
   * The walk order: newest first (`default`), `topo` (`--topo-order`, which
   * `--graph` implies) or `date` (`--date-order`).
   */
  readonly order: 'default' | 'topo' | 'date'
}

/** One commit of a walk: drawn by `--graph` always, printed unless `-S` passed it by. */
export interface WalkStep {
  readonly commit: CommitFacts
  readonly shown: boolean
}

/** The commits a log walks, in order, and the ones a graph may draw an edge to. */
export interface Walk {
  readonly steps: readonly WalkStep[]
  /**
   * Every commit in the walk that no filter leaves out, which is what makes
   * it a parent `--graph` draws a line to. Filled only for an ordered walk.
   */
  readonly interesting: ReadonlySet<string>
}

/**
 * Read a date flag as an epoch second, refusing what it cannot read.
 *
 * Accepts an ISO-8601 date or a bare epoch second. git accepts far more
 * (`2 weeks ago`, `yesterday`); anything else is refused here rather than
 * silently ignored, which would quietly widen the window.
 */
function timestamp(value: string | null, flag: string): number | null {
  if (value === null) return null
  const parsed = isoTimestamp(value)
  if (parsed !== null) return parsed
  const asNumber = Number(value)
  if (value.trim() !== '' && Number.isFinite(asNumber)) return asNumber
  throw new BadDateError(flag, value)
}

/**
 * Read display formats in command-line order, validating every occurrence.
 * --oneline sets the format; its abbreviation side effect is read separately.
 * Bare --pretty resets to medium, while bare --format is always an error
 * (Git 2.50.1).
 */
export function prettyFormat(fl: FlagView): LogFormat {
  let pretty: LogFormat = MEDIUM
  for (const [key, raw] of fl.occurrences('oneline', 'pretty', 'format')) {
    if (key === 'oneline') {
      if (raw === true) pretty = { kind: 'oneline', template: null }
    } else if (typeof raw === 'string') {
      pretty = parsePretty(raw)
    } else if (raw === true) {
      if (key === 'format') throw new UnrecognizedArgumentError('--format')
      pretty = MEDIUM
    }
  }
  return pretty
}

/** Read the raw log flag kwargs into a frozen struct. */
export function parseFlags(fl: FlagView): LogFlags {
  const oneline = fl.asBool('oneline')
  const pretty = prettyFormat(fl)
  const graph = fl.asBool('graph')
  if (graph && fl.asBool('reverse')) throw new IncompatibleLogOptionsError('--graph', '--reverse')
  let order: LogFlags['order'] = graph ? 'topo' : 'default'
  for (const name of fl.typedOrder('topo_order', 'date_order')) {
    if (fl.asBool(name)) order = name === 'topo_order' ? 'topo' : 'date'
  }
  let authors: RegExp[]
  try {
    authors = fl.asList('author').map(searchBre)
  } catch (err) {
    if (err instanceof BreError) throw new GitError(err.message)
    throw err
  }
  return {
    authors,
    date: fl.asStr('date') ?? 'default',
    decorate: fl.asBool('decorate'),
    maxCount: fl.asInt('n') ?? null,
    minParents: fl.asBool('merges') ? 2 : (fl.asInt('min_parents') ?? null),
    maxParents: fl.asBool('no_merges') ? 1 : (fl.asInt('max_parents') ?? null),
    firstParent: fl.asBool('first_parent'),
    oneline,
    reverse: fl.asBool('reverse'),
    search: fl.asStr('S') ?? null,
    since: timestamp(fl.asStr('after') ?? fl.asStr('since') ?? null, '--since'),
    until: timestamp(fl.asStr('before') ?? fl.asStr('until') ?? null, '--until'),
    allRefs: fl.asBool('all'),
    pretty,
    abbrevCommit: oneline,
    graph,
    order,
  }
}

/** Whether an isomorphic-git error means "not that object type". */
function isWrongType(err: unknown): boolean {
  return (
    typeof err === 'object' && err !== null && (err as { code?: string }).code === 'ObjectTypeError'
  )
}

/** Follow tag objects down to the commit a ref ultimately names. */
export async function peelToCommit(repo: Repo, oid: string): Promise<CommitFacts | null> {
  let cursor = oid
  for (;;) {
    try {
      const { tag } = await git.readTag({ ...repoArgs(repo), oid: cursor })
      cursor = tag.object
    } catch (err) {
      // Not a tag object: read it as a commit instead.
      if (isWrongType(err)) break
      throw err
    }
  }
  try {
    return await commitFacts(repo, cursor)
  } catch (err) {
    // A ref may name a tree or blob, which no log walks from.
    if (isWrongType(err)) return null
    throw err
  }
}

/** A ref table with symrefs resolved to the ids they name. */
export async function resolvedRefs(repo: Repo): Promise<Map<string, string>> {
  const refs = await loadRefs(repo.dispatch, repo.location.gitdir, repo.location.commondir)
  const out = new Map<string, string>()
  for (const [name, value] of refs) {
    const target = value.startsWith(SYMREF_PREFIX)
      ? refs.get(value.slice(SYMREF_PREFIX.length).trim())
      : value
    // A symref to an unborn branch names nothing yet.
    if (target !== undefined && !target.startsWith(SYMREF_PREFIX)) out.set(name, target)
  }
  return out
}

/** Every commit a ref points at, tags peeled, for `--all`. */
export async function refCommits(repo: Repo): Promise<CommitFacts[]> {
  const refs = await resolvedRefs(repo)
  const commits: CommitFacts[] = []
  for (const name of [...refs.keys()].sort(compareCodePoints)) {
    const oid = refs.get(name)
    if (oid === undefined) continue
    const commit = await peelToCommit(repo, oid)
    if (commit !== null) commits.push(commit)
  }
  return commits
}

/**
 * Ref labels per commit, in the order git prints them.
 *
 * git walks refs alphabetically and prepends each label, so a commit's labels
 * read in reverse ref order; HEAD is pulled to the front, spelled
 * `HEAD -> branch` when attached (the branch's own label is absorbed) and
 * `HEAD` alone when detached. Pinned against git 2.50.
 */
export async function decorations(repo: Repo): Promise<Map<string, string[]>> {
  const refs = await loadRefs(repo.dispatch, repo.location.gitdir, repo.location.commondir)
  const resolved = await resolvedRefs(repo)
  const labels = new Map<string, string[]>()
  for (const name of [...resolved.keys()].sort(compareCodePoints)) {
    if (name === HEAD) continue
    const oid = resolved.get(name)
    if (oid === undefined) continue
    const commit = await peelToCommit(repo, oid)
    if (commit === null) continue
    const list = labels.get(commit.oid) ?? []
    list.unshift(refLabel(name))
    labels.set(commit.oid, list)
  }
  await decorateHead(repo, refs, resolved, labels)
  return labels
}

/** One ref's decoration label, in git's spelling. */
function refLabel(name: string): string {
  if (name.startsWith(TAG_PREFIX)) return `tag: ${name.slice(TAG_PREFIX.length)}`
  if (name.startsWith(BRANCH_PREFIX)) return name.slice(BRANCH_PREFIX.length)
  if (name.startsWith(REMOTE_PREFIX)) return name.slice(REMOTE_PREFIX.length)
  return name
}

/** Prepend the HEAD label, absorbing the attached branch's own. */
async function decorateHead(
  repo: Repo,
  refs: ReadonlyMap<string, string>,
  resolved: ReadonlyMap<string, string>,
  labels: Map<string, string[]>,
): Promise<void> {
  const oid = resolved.get(HEAD)
  if (oid === undefined) return
  const commit = await peelToCommit(repo, oid)
  if (commit === null) return
  const list = labels.get(commit.oid) ?? []
  const raw = refs.get(HEAD) ?? ''
  if (raw.startsWith(SYMREF_PREFIX)) {
    const branch = refLabel(raw.slice(SYMREF_PREFIX.length).trim())
    const at = list.indexOf(branch)
    if (at !== -1) list.splice(at, 1)
    list.unshift(`HEAD -> ${branch}`)
  } else {
    list.unshift(HEAD)
  }
  labels.set(commit.oid, list)
}

/**
 * Walk history from a set of commits, newest first, along every parent.
 *
 * Ordered by committer time with ties broken by insertion, which is what a
 * git log without `--topo-order` prints. Each commit is visited once however
 * many branches reach it.
 *
 * A hidden commit takes its whole ancestry out of the walk, through every
 * parent even under `--first-parent`, which is how git carries a range's
 * exclusion. With anything hidden the walk is git's limited one: it holds what
 * it finds, so a commit that a later hidden one turns out to reach still drops
 * out, and it runs past the point where every queued commit is hidden by
 * git's slop of five hidden commits, restarted whenever one is dated no older
 * than the last shown one. That slack is what keeps a history whose dates run
 * backwards from leaking commits the hidden side reaches late.
 */
async function* walkHistory(
  repo: Repo,
  starts: readonly CommitFacts[],
  firstParent: boolean,
  hidden: readonly CommitFacts[] = [],
): AsyncGenerator<CommitFacts> {
  const seen = new Set<string>()
  const excluded = new Set<string>()
  const visited = new Map<string, CommitFacts>()
  const queue: CommitFacts[] = []
  const held: CommitFacts[] = []
  const hide = async (oids: readonly string[]): Promise<void> => {
    const stack = [...oids]
    for (let oid = stack.pop(); oid !== undefined; oid = stack.pop()) {
      if (excluded.has(oid)) continue
      excluded.add(oid)
      const known = visited.get(oid)
      if (known !== undefined) stack.push(...known.parents)
      else if (!seen.has(oid)) {
        seen.add(oid)
        queue.push(await commitFacts(repo, oid))
      }
    }
  }
  for (const commit of hidden) {
    if (seen.has(commit.oid)) continue
    seen.add(commit.oid)
    excluded.add(commit.oid)
    queue.push(commit)
  }
  for (const start of starts) {
    if (seen.has(start.oid)) continue
    seen.add(start.oid)
    queue.push(start)
  }
  const limited = hidden.length > 0
  let slop = SLOP
  let date = Infinity
  while (queue.length > 0) {
    queue.sort((a, b) => b.committerTime - a.committerTime)
    const next = queue.shift()
    if (next === undefined) break
    visited.set(next.oid, next)
    if (excluded.has(next.oid)) {
      await hide(next.parents)
      if (queue.length === 0) break
      const newest = queue.reduce((most, commit) => Math.max(most, commit.committerTime), -Infinity)
      if (date <= newest || !queue.every((commit) => excluded.has(commit.oid))) slop = SLOP
      else slop -= 1
      if (slop === 0) break
      continue
    }
    date = next.committerTime
    if (limited) held.push(next)
    else yield next
    for (const parent of firstParent ? next.parents.slice(0, 1) : next.parents) {
      if (seen.has(parent)) continue
      seen.add(parent)
      queue.push(await commitFacts(repo, parent))
    }
  }
  for (const commit of held) if (!excluded.has(commit.oid)) yield commit
}

/**
 * Order a walk's commits so no parent comes before any of its children.
 *
 * git's sort_in_topological_order: a commit is emitted once every child in
 * the list has been, children counted only among the commits listed. `topo`
 * keeps a stack, so a merge's second parent's line is followed to its end
 * before the first parent's, and the tips come out in walk order; `date`
 * takes the newest ready commit instead, ties in the order they became ready.
 *
 * @param list the walk, newest first
 * @param order which of git's two orders
 */
function sortCommits(list: readonly CommitFacts[], order: 'topo' | 'date'): CommitFacts[] {
  const indegree = new Map<string, number>()
  const byOid = new Map<string, CommitFacts>()
  for (const commit of list) {
    indegree.set(commit.oid, 1)
    byOid.set(commit.oid, commit)
  }
  for (const commit of list) {
    for (const parent of commit.parents) {
      const count = indegree.get(parent)
      if (count !== undefined && count > 0) indegree.set(parent, count + 1)
    }
  }
  // A stack for topo; for date a heap on (newest, first ready).
  const ready: { commit: CommitFacts; seq: number }[] = []
  let seq = 0
  const before = (a: number, b: number): boolean => {
    const x = ready[a]
    const y = ready[b]
    if (x === undefined || y === undefined) return false
    if (x.commit.committerTime !== y.commit.committerTime) {
      return x.commit.committerTime > y.commit.committerTime
    }
    return x.seq < y.seq
  }
  const swap = (a: number, b: number): void => {
    const x = ready[a]
    const y = ready[b]
    if (x === undefined || y === undefined) return
    ready[a] = y
    ready[b] = x
  }
  const put = (commit: CommitFacts): void => {
    ready.push({ commit, seq })
    seq += 1
    if (order === 'topo') return
    for (let at = ready.length - 1; at > 0 && before(at, (at - 1) >> 1); at = (at - 1) >> 1) {
      swap(at, (at - 1) >> 1)
    }
  }
  const take = (): CommitFacts | undefined => {
    if (order === 'topo' || ready.length <= 1) return ready.pop()?.commit
    const top = ready[0]
    const last = ready.pop()
    if (last !== undefined) ready[0] = last
    for (let at = 0; ; ) {
      let next = at
      for (const child of [2 * at + 1, 2 * at + 2]) {
        if (child < ready.length && before(child, next)) next = child
      }
      if (next === at) break
      swap(at, next)
      at = next
    }
    return top?.commit
  }
  for (const commit of list) if (indegree.get(commit.oid) === 1) put(commit)
  // The tips come out in the order the walk found them, which a stack
  // reverses unless it is turned over first.
  if (order === 'topo') ready.reverse()
  const sorted: CommitFacts[] = []
  for (let commit = take(); commit !== undefined; commit = take()) {
    for (const parent of commit.parents) {
      const count = indegree.get(parent)
      if (count === undefined || count === 0) continue
      indegree.set(parent, count - 1)
      const next = byOid.get(parent)
      if (count - 1 === 1 && next !== undefined) put(next)
    }
    indegree.set(commit.oid, 0)
    sorted.push(commit)
  }
  return sorted
}

/** Whether a commit's date is inside `--since`/`--until`. */
function inWindow(commit: CommitFacts, flags: LogFlags): boolean {
  if (flags.since !== null && commit.committerTime < flags.since) return false
  return flags.until === null || commit.committerTime <= flags.until
}

/** Whether a commit's author and parent count pass `--merges`, `--no-merges` and kin. */
function filtersPass(commit: CommitFacts, flags: LogFlags): boolean {
  if (
    flags.authors.length &&
    !flags.authors.some((pattern) => pattern.test(`${commit.authorName} <${commit.authorEmail}>`))
  )
    return false
  if (flags.minParents !== null && commit.parents.length < flags.minParents) return false
  return !(
    flags.maxParents !== null &&
    flags.maxParents >= 0 &&
    commit.parents.length > flags.maxParents
  )
}

/**
 * The commits a log walks, in the order it walks them.
 *
 * Order of operations is git's: walk history, drop what the filters reject,
 * and cut at `-n` printed commits. A topological or date order needs the whole
 * walk first (git's limited walk), and is taken over the commits inside the
 * date window before the other filters run. The pickaxe is the one filter that
 * leaves a commit in the walk: git still draws it into the graph and only
 * declines to print it, which is why `--graph -S` shows `...` rows.
 *
 * @param repo repository to walk
 * @param starts the commits to walk back from; more than one when `--all`
 *   seeds every ref
 * @param flags the parsed invocation
 * @param hidden commits whose whole history is left out, the `A` of `A..B`
 */
export async function walked(
  repo: Repo,
  starts: readonly CommitFacts[],
  flags: LogFlags,
  hidden: readonly CommitFacts[] = [],
): Promise<Walk> {
  const steps: WalkStep[] = []
  const interesting = new Set<string>()
  if (flags.maxCount === 0) return { steps, interesting }
  let source: AsyncIterable<CommitFacts> | Iterable<CommitFacts> = walkHistory(
    repo,
    starts,
    flags.firstParent,
    hidden,
  )
  if (flags.order !== 'default') {
    const window: CommitFacts[] = []
    for await (const commit of source) if (inWindow(commit, flags)) window.push(commit)
    for (const commit of window) if (filtersPass(commit, flags)) interesting.add(commit.oid)
    source = sortCommits(window, flags.order)
  }
  let printed = 0
  for await (const commit of source) {
    if (!inWindow(commit, flags) || !filtersPass(commit, flags)) continue
    const shown =
      flags.search === null || (await touches(repo, commit.oid, commit.parents, flags.search))
    steps.push({ commit, shown })
    if (shown) printed += 1
    if (flags.maxCount !== null && printed >= flags.maxCount) break
  }
  return { steps, interesting }
}

/**
 * The commits a log invocation prints, in the order it prints them.
 *
 * The walk's printed commits, reversed last when asked: reversing after the
 * cut is what makes `-S <name> --reverse` name the commit that introduced a
 * string rather than the most recent one to touch it.
 *
 * @param repo repository to walk
 * @param starts the commits to walk back from
 * @param flags the parsed invocation
 * @param hidden commits whose whole history is left out, the `A` of `A..B`
 */
export async function select(
  repo: Repo,
  starts: readonly CommitFacts[],
  flags: LogFlags,
  hidden: readonly CommitFacts[] = [],
): Promise<CommitFacts[]> {
  const selected = (await walked(repo, starts, flags, hidden)).steps
    .filter((step) => step.shown)
    .map((step) => step.commit)
  if (flags.reverse) selected.reverse()
  return selected
}
