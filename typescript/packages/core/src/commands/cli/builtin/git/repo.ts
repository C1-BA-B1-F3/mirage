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

import type { FlagView } from '../../../spec/flag_view.ts'
import { discover, requireWorkTree } from './discover.ts'
import { NoWorkspaceError } from './errors.ts'
import { abbrevLength, type CommitFacts } from './format.ts'
import { configValues, gitFs } from './fs.ts'
import { exists, readNames, readRange, under, writeFile } from './io.ts'
import { basename } from './path.ts'
import type { CLIDoors } from '../../types.ts'
import { gitBool, startPoint } from './util.ts'
import type { Dispatch, RepoLocation } from './types.ts'

const PACK_DIR = 'objects/pack'
const IDX_SUFFIX = '.idx'
// A v2 pack index is a 8-byte header then 256 fanout entries; the last one is
// the object count, so the total is four bytes at a fixed offset.
const FANOUT_END = 8 + 256 * 4

/**
 * A repository living in a mount, opened for reading.
 *
 * `fs` is the whole bridge: isomorphic-git reaches every byte through it, so its
 * own algorithms (history walk, tree diff, three-way merge) run against a mount
 * without ever learning that one exists. Nothing here is loaded eagerly, which
 * is also what git does.
 *
 * Objects come from the common directory and refs from both: a linked worktree
 * shares the object database and the branches of the repository it was cut from,
 * and owns only HEAD and whatever refs are per-checkout.
 */
export interface Repo {
  readonly fs: ReturnType<typeof gitFs>
  readonly dispatch: Dispatch
  readonly location: RepoLocation
  /** Parsed packs shared by this invocation, never retained across commands. */
  readonly cache: Record<symbol, unknown>
  /** How many hex digits this repository abbreviates an id to. */
  readonly abbrev: number
}

/** The argument bag every isomorphic-git call in this package shares. */
export function repoArgs(repo: Repo): {
  fs: never
  dir: string
  gitdir: string
  cache: Repo['cache']
} {
  return {
    fs: repo.fs as never,
    dir: repo.location.worktree,
    gitdir: repo.location.gitdir,
    cache: repo.cache,
  }
}

/**
 * How many objects the repository's packs hold, for the id abbreviation.
 *
 * Read off each pack index, which states its own count in its fanout table, so
 * this costs one small ranged read per pack. Loose objects are deliberately not
 * counted: git's own estimate ignores them, and matching that is what makes an
 * abbreviated id agree with real git.
 */
async function packedCount(dispatch: Dispatch, commondir: string): Promise<number> {
  const root = under(commondir, PACK_DIR)
  let total = 0
  for (const entry of await readNames(dispatch, root)) {
    const name = basename(entry)
    if (!name.endsWith(IDX_SUFFIX)) continue
    const head = await readRange(dispatch, under(root, name), FANOUT_END - 4, 4)
    if (head.byteLength < 4) continue
    total += new DataView(head.buffer, head.byteOffset, 4).getUint32(0, false)
  }
  return total
}

/** Which of commit/tag/tree/blob an id names, null when the repository lacks it. */
export async function objectType(repo: Repo, oid: string): Promise<string | null> {
  try {
    // Deprecated upstream for being general, but the general answer is what a
    // walk needs: which kind this id names, without reading it as each in turn
    // until one does not throw.
    // eslint-disable-next-line @typescript-eslint/no-deprecated
    return (await git.readObject({ ...repoArgs(repo), oid, format: 'content' })).type
  } catch {
    return null
  }
}

/**
 * Keep a fetched pack whole, beside the index git reads it through.
 *
 * Named by the pack's own checksum, as git names one it receives, and indexed
 * after the pack is written, so a reader that lists `.idx` files never finds
 * one whose pack is not there yet. An empty pack stores nothing.
 */
export async function storePack(repo: Repo, data: Uint8Array): Promise<void> {
  if (!data.length) return
  const checksum = [...data.subarray(data.length - 20)]
    .map((byte) => byte.toString(16).padStart(2, '0'))
    .join('')
  const dir = under(repo.location.commondir, PACK_DIR)
  const name = `pack-${checksum}.pack`
  if (await exists(repo.dispatch, under(dir, name.replace(/\.pack$/, IDX_SUFFIX)))) return
  await writeFile(repo.dispatch, under(dir, name), data)
  await git.indexPack({ ...repoArgs(repo), dir, filepath: name })
}

/**
 * Open a repository living in a mount.
 *
 * @param dispatch workspace op dispatcher
 * @param location the discovered repository
 */
export async function openRepo(dispatch: Dispatch, location: RepoLocation): Promise<Repo> {
  return {
    fs: gitFs(dispatch, location),
    dispatch,
    location,
    cache: {},
    abbrev: abbrevLength(await packedCount(dispatch, location.commondir)),
  }
}

/**
 * Discover and open the repository a verb was invoked against.
 *
 * Every verb starts the same way: honor `-C`, walk up to the mount root looking
 * for a `.git`, then open the object database across the dispatcher. Kept in one
 * place so a new verb inherits the discovery rules rather than restating them.
 *
 * @param fl the leaf's flag bag, read for `-C`, `--git-dir` and `--work-tree`
 * @param doors the invocation's doors, one per state plane
 * @param workTree the verb reads or writes working files, so there must be a
 *   work tree to enter, as git's `NEED_WORK_TREE` asks
 */
export async function opened(fl: FlagView, doors: CLIDoors, workTree = false): Promise<Repo> {
  const dispatch = doors.dispatch
  const statPath = doors.statPath
  // The mount root comes from the name plane rather than a door of its own:
  // `ns.mounts.rootOf` is the same fact the command tier reads, and a second
  // field holding the same callable is a second thing to keep in step.
  const mounts = doors.ns?.mounts
  if (statPath === undefined || mounts === undefined || dispatch === undefined) {
    throw new NoWorkspaceError()
  }
  const chosen = fl.asStr('work_tree')
  const location = await discover(
    dispatch,
    statPath,
    (path: string) => mounts.rootOf(path),
    startPoint(fl),
    fl.asStr('git_dir'),
    chosen,
  )
  if (workTree) await requireWorkTree(dispatch, statPath, location, chosen !== undefined)
  return openRepo(dispatch, location)
}

/**
 * One commit as the renderers want it.
 *
 * isomorphic-git reports the timezone the way `Date.getTimezoneOffset()` does,
 * negated minutes east of UTC, so `+0530` arrives as `-330`. git prints the
 * other sign, and this is the one place the two conventions meet.
 */
export async function commitFacts(repo: Repo, oid: string): Promise<CommitFacts> {
  const { commit } = await git.readCommit({ ...repoArgs(repo), oid })
  return {
    oid,
    tree: commit.tree,
    message: commit.message,
    authorName: commit.author.name,
    authorEmail: commit.author.email,
    authorTime: commit.author.timestamp,
    authorTimezoneMinutes: -commit.author.timezoneOffset,
    committerName: commit.committer.name,
    committerEmail: commit.committer.email,
    committerTime: commit.committer.timestamp,
    committerTimezoneMinutes: -commit.committer.timezoneOffset,
    parents: commit.parent,
  }
}

/**
 * A boolean from the repository's config, read the way git reads one.
 *
 * @param repo the opened repository
 * @param path the variable, e.g. `core.quotepath`
 * @param fallback the answer when the variable is unset
 */
export async function configBool(repo: Repo, path: string, fallback: boolean): Promise<boolean> {
  const values = await configValues(repo.dispatch, repo.location, path)
  return gitBool(values, path.toLowerCase(), fallback)
}
