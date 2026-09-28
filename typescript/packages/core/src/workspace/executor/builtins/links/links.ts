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

import { destKind } from '../../../../commands/builtin/generic/cp.ts'
import { FlagView, SPECS, parseCommand } from '../../../../commands/spec/index.ts'
import { parseToKwargs } from '../../../../commands/spec/parser.ts'
import type { FileStat } from '../../../../types.ts'
import { FileType, PathSpec } from '../../../../types.ts'
import {
  ELOOP_STRERROR,
  fsStrerror,
  isEacces,
  isEnoent,
  isEnotdir,
  isErofs,
  isFsError,
} from '../../../../utils/errors.ts'
import { CycleError, gnuBasename, posixNormpath } from '../../../../utils/path.ts'
import { rstripSlash } from '../../../../utils/slash.ts'
import type { DispatchFn } from '../../../../runtime/types.ts'
import type { Namespace } from '../../../mount/namespace/namespace.ts'
import { fail, ok, splitFlags } from '../shared.ts'
import { dispatchStat } from '../../../../commands/builtin/utils/paths.ts'
import { statOrNull } from './probe.ts'
import type { MvMove, Result } from '../types.ts'
import type { FlagValue } from '../../../../commands/spec/types.ts'

export function posixRelative(target: string, startDir: string): string {
  const t = target.split('/').filter(Boolean)
  const s = startDir.split('/').filter(Boolean)
  let i = 0
  while (i < t.length && i < s.length && t[i] === s[i]) i += 1
  const parts = [...s.slice(i).map(() => '..'), ...t.slice(i)]
  return parts.length > 0 ? parts.join('/') : '.'
}

export function linkFlags(args: (string | PathSpec)[], known: string): Set<string> {
  return splitFlags(args, known)[0]
}

// Resolve every component of a path but the last one. POSIX resolves a
// path one component at a time, and only the last one is exempt for an
// lstat-style command: `stat dlink/f2` reports f2 because dlink was
// resolved on the way to it, while `stat dlink` reports the link. A
// no-follow command therefore still needs its operand's prefix
// resolved. The walk is the namespace's (`Namespace.followParent`, which
// the op door runs for every surface); the operand comes back without a
// trailing slash, which the slash-keeping commands read off `rawPath`
// instead. Throws CycleError on ELOOP.
function followParent(namespace: Namespace, virtual: string): string {
  const trimmed = rstripSlash(virtual)
  return trimmed === '' ? virtual : namespace.followParent(trimmed)
}

// Rewrite path operands through the symlink table (open(2) semantics).
// The directory prefix always resolves; `followLast` decides the final
// component, which is the whole difference between open(2) and lstat(2).
// A trailing slash overrides it per operand, because POSIX reads
// `dlink/` as `dlink/.` and there is no `.` to reach without resolving
// the link first (GNU: `stat dlink` is a symbolic link, `stat dlink/` is
// a directory). `slashFollows` turns that override off, which only tar
// wants: it strips the slash before it stats.
// A rewritten spec keeps the user-typed form in `rawPath` so error messages
// still name the operand as typed; the mount re-stamps `vfsPath` at
// dispatch. A path a link loop stands in resolves to nothing, so it stays
// as typed with `walkError` set, and the op that reaches it answers ELOOP:
// GNU reports the one operand in the command's own words and goes on to
// the next.
export function followPaths(
  namespace: Namespace,
  items: (string | PathSpec)[],
  followLast = true,
  slashFollows = true,
): (string | PathSpec)[] {
  const out: (string | PathSpec)[] = []
  for (const item of items) {
    if (!(item instanceof PathSpec)) {
      out.push(item)
      continue
    }
    const last = followLast || (slashFollows && item.rawPath.endsWith('/'))
    let followed: string
    try {
      followed = last ? namespace.follow(item.virtual) : followParent(namespace, item.virtual)
    } catch (err) {
      if (!(err instanceof CycleError)) throw err
      out.push(
        new PathSpec({
          virtual: item.virtual,
          directory: item.directory,
          vfsPath: item.vfsPath,
          pattern: item.pattern,
          resolved: item.resolved,
          rawPath: item.rawPath,
          dotted: item.dotted,
          walkError: 'ELOOP',
        }),
      )
      continue
    }
    // A relative target climbs from the link's own directory, which is a real
    // one, so its `..` collapses the way resolveLink collapses it; left in,
    // the path no longer matched the word that spelled it and the operand lost
    // its typed name (`wc -c sub/al` printed `/data/sub/../a`).
    let virtual = posixNormpath(followed)
    if (followed.endsWith('/') && virtual !== '/') virtual += '/'
    if (virtual === item.virtual) {
      out.push(item)
      continue
    }
    out.push(
      new PathSpec({
        virtual,
        directory: virtual.slice(0, virtual.lastIndexOf('/') + 1) || '/',
        vfsPath: '',
        pattern: item.pattern,
        resolved: item.resolved,
        rawPath: item.rawPath,
        dotted: item.dotted,
        walkError: item.walkError,
      }),
    )
  }
  return out
}

// Whether the command layer will act on this line as written.
//
// A link entry lives in the namespace, so `stripLinkOperands` removes it
// before the command runs, and the command layer can neither see that nor
// undo it. GNU validates the whole line first and removes nothing when it
// refuses: `rm --bogus dlink` reports the option and `unlink dlink other`
// reports the extra operand, both with every link still in place. So the
// strip runs only for a line that layer accepts, and a refused one falls
// through to it unchanged to be reported there. Option errors are the
// parser's, which reports rather than raises them; unlink's one-operand
// grammar is its builder's, and reporting it needs the operands to arrive
// intact.
export function acceptsLine(
  name: string,
  args: readonly string[],
  items: (string | PathSpec)[],
  cwd: string,
): boolean {
  const spec = SPECS[name]
  if (spec === undefined) return true
  const parsed = parseCommand(spec, [...args], cwd, name)
  if (parsed.invalidOptions.length > 0 || parsed.ambiguousOptions.length > 0) {
    return false
  }
  if (name === 'unlink') {
    return items.filter((i) => i instanceof PathSpec).length <= 1
  }
  return true
}

// Unlink and drop `rm`/`unlink` operands that are symlinks. GNU rm removes
// the link itself and never follows it; a dangling link removes fine.
//
// The removal is a dispatch op, never a direct table write: the door is
// where session grants, the turf's mode, admission policies and the op
// ledger fire, and writing the table from here let a session delete a
// link its grant reads and a policy protecting one never fired (the same
// hole the FUSE unlink had). A refused operand does not stop the rest,
// which is also rm's rule for a backend operand; `-f` silences only the
// absent (a hidden link answers ENOENT, the no-name-leak rule).
//
// The refusal is voiced the way the same refusal on a backend file is
// voiced, so one grant does not describe itself two ways: GNU's
// per-operand line, a read-only region's EROFS included.
//
// An operand typed with a trailing slash is deliberately kept: the slash
// asked for a directory, and GNU refuses rather than removing the link
// (`rm dlink/` is "Is a directory", `unlink dlink/` is "Not a
// directory"). Removing it here would delete exactly what the slash was
// protecting, so the command reports it instead. Returns the surviving
// parts, the number of link operands consumed (removed, refused or
// force-silenced), and the refusal lines. Mirrors Python's
// strip_link_operands.
export async function stripLinkOperands(
  name: string,
  dispatch: DispatchFn,
  namespace: Namespace,
  items: (string | PathSpec)[],
  args: readonly string[],
  cwd: string,
): Promise<[(string | PathSpec)[], number, string[]]> {
  let force = false
  if (name === 'rm') {
    const spec = SPECS.rm
    if (spec !== undefined) {
      // Keyed by the dashed spelling the line used, not the dest.
      force = parseCommand(spec, [...args], cwd, 'rm').flags['-f'] === true
    }
  }
  const verb = name === 'rm' ? 'remove' : 'unlink'
  let handled = 0
  const errors: string[] = []
  const kept: (string | PathSpec)[] = []
  for (const item of items) {
    if (item instanceof PathSpec && !item.rawPath.endsWith('/') && namespace.isLink(item.virtual)) {
      handled += 1
      try {
        await dispatch('unlink', item)
      } catch (err) {
        const suffix = fsStrerror(err)
        if (suffix === null) throw err
        if (isEnoent(err) && force) continue
        errors.push(`${name}: cannot ${verb} '${item.rawPath}': ${suffix}\n`)
      }
      continue
    }
    kept.push(item)
  }
  return [kept, handled, errors]
}

// GNU's refusal for an `mv` source that is a link typed with a slash.
//
// rename(2) never follows, so the slash is not resolved away: POSIX reads
// `dlink/` as `dlink/.`, which asks for a directory the call will not
// resolve, and GNU refuses with everything left in place -- where a bare
// `dlink` renames the link entry. Which of the four wordings applies
// follows mv's own order, source stat before destination type before the
// rename itself, and all four are pinned against GNU coreutils 9.7.
async function slashedLinkRefusal(
  namespace: Namespace,
  dispatch: DispatchFn,
  src: PathSpec,
  dst: PathSpec,
  dstStat: FileStat | null,
): Promise<Result> {
  let followed: string
  try {
    followed = namespace.follow(src.virtual)
  } catch (err) {
    if (!(err instanceof CycleError)) throw err
    return fail('mv', `mv: cannot stat '${src.rawPath}': ${ELOOP_STRERROR}\n`)
  }
  const target = await statOrNull(dispatch, PathSpec.fromStrPath(followed))
  if (target === null) {
    return fail('mv', `mv: cannot stat '${src.rawPath}': No such file or directory\n`)
  }
  if (target.type !== FileType.DIRECTORY) {
    return fail('mv', `mv: cannot stat '${src.rawPath}': Not a directory\n`)
  }
  if (dstStat !== null && dstStat.type !== FileType.DIRECTORY) {
    return fail(
      'mv',
      `mv: cannot overwrite non-directory '${dst.rawPath}' with directory '${src.rawPath}'\n`,
    )
  }
  let landing = dst.rawPath
  if (dstStat !== null) {
    landing = rstripSlash(landing) + '/' + gnuBasename(src.virtual)
  }
  return fail('mv', `mv: cannot move '${src.rawPath}' to '${landing}': Not a directory\n`)
}

/**
 * Resolve each command-line link that leads to a directory: GNU ls's default
 * (ls.c's DEREF_COMMAND_LINE_SYMLINK_TO_DIR, coreutils 9.7). `ls dlink` lists
 * the directory, while `ls flink` and a dangling `ls dang` report the link
 * itself, and so does a loop, whose stat fails where GNU then lstats it.
 * Where a link leads takes a stat through the door to know, since the target
 * may live on any mount, so this runs after `followPaths` has resolved every
 * operand's prefix. Mirrors Python's follow_directory_links.
 */
export async function followDirectoryLinks(
  namespace: Namespace,
  dispatch: DispatchFn,
  items: readonly (string | PathSpec)[],
): Promise<(string | PathSpec)[]> {
  const out: (string | PathSpec)[] = []
  for (const item of items) {
    if (!(item instanceof PathSpec) || item.walkError !== null || !namespace.isLink(item.virtual)) {
      out.push(item)
      continue
    }
    const followed = followPaths(namespace, [item])[0]
    const target =
      followed instanceof PathSpec && followed.walkError === null
        ? await statOrNull(dispatch, followed)
        : null
    out.push(
      target !== null && target.type === FileType.DIRECTORY && followed !== undefined
        ? followed
        : item,
    )
  }
  return out
}

export interface PreparedMv {
  items: (string | PathSpec)[]
  // The pairs whose node entries follow the bytes once each move is confirmed.
  moves: MvMove[]
  // Set when the line completed as namespace renames.
  early: Result | null
  // Lines for link sources the rename refused.
  errors: string[]
}

// Adjust an `mv` line for node-meta operands. A link source renames the link
// entry itself. A destination that is (a link to) a directory receives the
// move inside it (rename(2) preceded by mv's dst stat); any other destination
// is replaced, so its node entry, link or overlay attrs alike, drops once the
// backend move succeeds. A plain source hands back the pair to re-anchor once
// the backend move succeeds, so whatever the node table holds at it and below
// it travels with the bytes.
//
// This has to be done here: a single-mount `mv` renames through the backend op
// bound to the accessor rather than through the dispatcher, so the re-anchoring
// the dispatcher does for every other caller has to be repeated. `-t` and `-T`
// are read off the parsed line rather than guessed from the parts, since a
// path-shaped flag value is classified into a PathSpec exactly as an operand
// is. Mirrors Python's prepare_mv.
export async function prepareMv(
  namespace: Namespace,
  dispatch: DispatchFn,
  items: (string | PathSpec)[],
  args: readonly string[],
  cwd: string,
): Promise<PreparedMv> {
  const paths = items.filter((p): p is PathSpec => p instanceof PathSpec)
  const spec = SPECS.mv
  if (spec === undefined) return { items, moves: [], early: null, errors: [] }
  const fl = new FlagView(parseToKwargs(parseCommand(spec, [...args], cwd, 'mv')), spec)
  const target = fl.raw('target_directory')
  if (target !== undefined || paths.length > 2) {
    return prepareMany(namespace, dispatch, items, paths, target)
  }
  const src = paths[0]
  const dst = paths[1]
  if (paths.length !== 2 || src === undefined || dst === undefined) {
    return { items, moves: [], early: null, errors: [] }
  }
  return { ...(await preparePair(namespace, dispatch, items, src, dst, fl)), errors: [] }
}

/**
 * Carry the node table across the moves the backend completed. A move is
 * confirmed by its landing, because a several-source mv can fail one source
 * and move the rest: a landing that appeared is a move that happened. A
 * landing that was already there (a link included, which shadows whatever
 * lands under its name) is replaced by the move, which only the line's status
 * can confirm. The source cannot confirm anything, since a link left below a
 * moved directory synthesizes that directory back. The landing
 * is replaced the way rename(2) replaces it, node and subtree alike, and then
 * the source's own node and subtree land on it, the same four steps the
 * dispatcher takes for a rename it forwards itself. Mirrors Python's
 * settle_moves.
 */
export async function settleMoves(
  namespace: Namespace,
  dispatch: DispatchFn,
  moves: readonly MvMove[],
  exitCode: number,
): Promise<void> {
  for (const [src, landing, replaced] of moves) {
    if (replaced ? exitCode !== 0 : !(await present(dispatch, landing))) continue
    await namespace.unlink(landing)
    await namespace.purgeUnder(landing)
    await namespace.rename(src, landing)
    await namespace.renameUnder(src, landing)
  }
}

// Whether a path resolves to an entry; a link loop resolves to none, which
// statOrNull already answers as null. Mirrors Python's _present.
async function present(dispatch: DispatchFn, virtual: string): Promise<boolean> {
  return (await statOrNull(dispatch, PathSpec.fromStrPath(virtual))) !== null
}

// Each [source, landing] pair, with whether the landing is already there,
// which settleMoves reads to confirm the move. Mirrors Python's _moves.
async function movesOf(
  namespace: Namespace,
  dispatch: DispatchFn,
  pairs: readonly (readonly [PathSpec, string])[],
): Promise<MvMove[]> {
  const moves: MvMove[] = []
  for (const [src, landing] of pairs) {
    const there = namespace.isLink(landing) || (await present(dispatch, landing))
    moves.push([src.virtual, landing, there])
  }
  return moves
}

function landingKey(path: string): string {
  return rstripSlash(path) || '/'
}

/**
 * An `mv` of sources into one destination directory: `mv a b dst` and
 * `mv -t dst a ...`. GNU stats the destination through its link before
 * anything moves: a link to a directory takes the sources, a link to anything
 * else is not a directory, a dangling one is missing and a loop is ELOOP, each
 * worded by the generic mv from the destination handed to it here (coreutils
 * 9.7). Every source then lands at the directory plus its basename: a link
 * source through the namespace, which no backend mv can see, and every other
 * one with its node entries re-anchored once the backend confirms the move.
 * Mirrors Python's _prepare_many.
 */
async function prepareMany(
  namespace: Namespace,
  dispatch: DispatchFn,
  items: (string | PathSpec)[],
  paths: readonly PathSpec[],
  target: FlagValue | undefined,
): Promise<PreparedMv> {
  let dst: PathSpec | undefined
  let sources: PathSpec[]
  if (target !== undefined) {
    const spelled =
      target instanceof PathSpec ? target.virtual : typeof target === 'string' ? target : null
    dst =
      spelled === null
        ? undefined
        : paths.find((p) => landingKey(p.virtual) === landingKey(spelled))
    sources = paths.filter((p) => p !== dst)
  } else {
    dst = paths[paths.length - 1]
    sources = paths.slice(0, -1)
  }
  if (dst?.walkError !== null) {
    return { items, moves: [], early: null, errors: [] }
  }
  const followed = followPaths(namespace, [dst])[0]
  if (!(followed instanceof PathSpec)) return { items, moves: [], early: null, errors: [] }
  let rewritten = items.map((item) => (item === dst ? followed : item))
  if (followed.walkError !== null) return { items: rewritten, moves: [], early: null, errors: [] }
  const stat = await statOrNull(dispatch, PathSpec.fromStrPath(followed.virtual))
  if (stat?.type !== FileType.DIRECTORY) {
    return { items: rewritten, moves: [], early: null, errors: [] }
  }
  const base = rstripSlash(followed.virtual)
  const typed = rstripSlash(dst.rawPath)
  const pairs: [PathSpec, string][] = []
  const errors: string[] = []
  for (const src of sources) {
    if (src.walkError !== null) continue
    const landing = `${base}/${gnuBasename(rstripSlash(src.virtual))}`
    if (!namespace.isLink(src.virtual) || src.rawPath.endsWith('/')) {
      pairs.push([src, landing])
      continue
    }
    // A link has no backend entry for the generic mv to move, so the door
    // renames it, where every other mv's admission gates apply.
    rewritten = rewritten.filter((item) => item !== src)
    try {
      await dispatch('rename', src, [PathSpec.fromStrPath(landing)])
    } catch (err) {
      if (!isFsError(err)) throw err
      const shown = `${typed}/${gnuBasename(rstripSlash(src.rawPath))}`
      errors.push(`mv: cannot move '${src.rawPath}' to '${shown}': ${String(fsStrerror(err))}\n`)
    }
  }
  if (!rewritten.some((item) => item instanceof PathSpec && item !== followed)) {
    // Every source was a link, so the namespace finished the line.
    const early = errors.length > 0 ? fail('mv', errors.join('')) : ok('mv')
    return { items: rewritten, moves: [], early, errors: [] }
  }
  return { items: rewritten, moves: await movesOf(namespace, dispatch, pairs), early: null, errors }
}

// A two-operand `mv`: one source and the destination it replaces or lands
// inside. Mirrors Python's _prepare_pair.
async function preparePair(
  namespace: Namespace,
  dispatch: DispatchFn,
  items: (string | PathSpec)[],
  src: PathSpec,
  dst: PathSpec,
  fl: FlagView,
): Promise<Omit<PreparedMv, 'errors'>> {
  if (src.walkError !== null || dst.walkError !== null) {
    // The walk refused the operand, so there is no entry to move or land
    // on; the generic mv reports it through its own stat, which cannot see
    // a link source. A link is a non-directory, and GNU stats an empty
    // destination as a directory (see mvGeneric).
    if (dst.rawPath === '' && src.walkError === null && namespace.isLink(src.virtual)) {
      const early = fail(
        'mv',
        `mv: cannot overwrite directory '' with non-directory '${src.rawPath}'\n`,
      )
      return { items, moves: [], early }
    }
    if (dst.walkError === 'ELOOP' && src.walkError === null && namespace.isLink(src.virtual)) {
      const early = fail('mv', `mv: cannot stat '${dst.rawPath}': ${ELOOP_STRERROR}\n`)
      return { items, moves: [], early }
    }
    return { items, moves: [], early: null }
  }

  // Where the move lands: inside a directory destination (followed, so
  // node-meta keys line up with the followed paths stat merges on), else
  // the destination itself, replaced like rename(2). A destination a link
  // loop stands in stats ELOOP, which mv reads as not a directory: the
  // rename replaces the link itself (GNU 9.7).
  let followed: string | null
  try {
    followed = namespace.follow(dst.virtual)
  } catch (err) {
    if (!(err instanceof CycleError)) throw err
    followed = null
  }
  const stat = followed === null ? null : await statOrNull(dispatch, PathSpec.fromStrPath(followed))
  const intoDir =
    !fl.asBool('no_target_directory') && stat !== null && stat.type === FileType.DIRECTORY
  let targetDst = dst.virtual
  if (intoDir && followed !== null) {
    const name = src.virtual.slice(src.virtual.lastIndexOf('/') + 1)
    targetDst = rstripSlash(followed) + '/' + name
  }

  if (namespace.isLink(src.virtual)) {
    if (src.rawPath.endsWith('/')) {
      const early = await slashedLinkRefusal(namespace, dispatch, src, dst, stat)
      return { items, moves: [], early }
    }
    if (!intoDir && dst.rawPath.endsWith('/')) {
      // rename(2) never follows the source, so a link is not a directory
      // whatever it points at, and a slashed destination asks for one:
      // GNU 9.7 refuses `mv dlnk missing/` at the rename and `mv dlnk reg/`
      // at the destination's stat, the same two wordings a regular source
      // gets from the generic, whose chain walk also keeps an absent
      // parent's ENOENT (`mv dlnk nodir/name/`) ahead of the slash.
      const { strerror } = await destKind(dispatchStat(dispatch), dst)
      const early =
        strerror === 'Not a directory'
          ? fail('mv', `mv: cannot stat '${dst.rawPath}': Not a directory\n`)
          : fail(
              'mv',
              `mv: cannot move '${src.rawPath}' to '${dst.rawPath}': ${strerror ?? 'Not a directory'}\n`,
            )
      return { items, moves: [], early }
    }
    // The move is a node-table rename, which the door answers: a link
    // has no backend entry for the generic mv to move. Reaching the
    // table directly from here would skip the admission gates every
    // other mv passes, so the dispatch is the point.
    try {
      await dispatch('rename', src, [PathSpec.fromStrPath(targetDst)])
    } catch (err) {
      const suffix = fsStrerror(err)
      if (suffix !== null && isEnotdir(err)) {
        // A plain file in the landing's chain, which GNU meets at the
        // destination's stat, before any rename.
        const early: Result = fail(
          'mv',
          `mv: cannot stat '${dst.rawPath}': ${suffix}
`,
        )
        return { items, moves: [], early }
      }
      if (suffix === null || (!isEacces(err) && !isErofs(err) && !isEnoent(err))) throw err
      // An absent landing parent, met at the rename as the generic mv words
      // it for a regular file, or a read-only endpoint or a policy deny,
      // which GNU voices per operand and the backend mv path voices the
      // same way.
      const early: Result = fail(
        'mv',
        `mv: cannot move '${src.rawPath}' to '${dst.rawPath}': ${suffix}\n`,
      )
      return { items, moves: [], early }
    }
    const early: Result = ok('mv')
    return { items, moves: [], early }
  }

  // Unconditional on what the table holds: a directory source carries a whole
  // subtree of node entries that no exact-path lookup at the source can see,
  // and a symlink below it is destroyed rather than merely forgotten when they
  // are left behind.
  const moves = await movesOf(namespace, dispatch, [[src, targetDst]])

  const rewritten = intoDir && namespace.isLink(dst.virtual) ? followPaths(namespace, items) : items
  return { items: rewritten, moves, early: null }
}
