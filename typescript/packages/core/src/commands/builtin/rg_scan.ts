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

import type { FileStat, PathSpec } from '../../types.ts'
import { FileType } from '../../types.ts'
import { fsStrerror, isWalkError } from '../../utils/errors.ts'
import { classify } from '../../errors/classify.ts'
import { posixErrno } from '../../errors/posix.ts'
import { gnuBasename, respellOne } from '../../utils/path.ts'
import { getExtension } from '../resolve.ts'
import { BINARY_EXTENSIONS } from './constants.ts'
import type { FileTypes } from './rg_filetypes.ts'
import { type Overrides, Verdict, walkCandidate } from './rg_glob.ts'
import type { AsyncReaddirFn, AsyncStatFn } from './utils/types.ts'
import { rstripSlash } from '../../utils/slash.ts'

/**
 * What ripgrep's walker keeps below a directory operand. The ignore crate's
 * order: a `-g` glob decides first and outranks everything after it, then
 * `-t`/`-T`, and a dot entry is left out unless a glob or a `-t` type kept
 * it or `--hidden` is on. A file is also left out past `--max-filesize`,
 * and for a binary extension unless `-a`/`--binary` asked for it. A name on
 * the line is never filtered: only walked entries are. `maxDepth` is the
 * deepest entry kept (1 is the operand's own children).
 */
export class WalkFilter {
  constructor(
    readonly overrides: Overrides,
    readonly types: FileTypes,
    readonly hidden: boolean,
    readonly maxDepth: number | null,
    readonly maxFilesize: number | null,
    readonly binary: boolean,
  ) {}

  // Whether a walked entry is kept (a directory: descended). `candidate`
  // is its path as the globs match it, `name` its file name.
  admits(candidate: string, name: string, isDir: boolean): boolean {
    const verdict = this.overrides.verdict(candidate, isDir)
    if (verdict === Verdict.IGNORE) return false
    if (verdict === Verdict.WHITELIST) return true
    const typed = this.types.verdict(name, isDir)
    if (typed === Verdict.IGNORE) return false
    return typed === Verdict.WHITELIST || this.hidden || !name.startsWith('.')
  }

  // Whether a walked file is searched, its stat read when the walk has one.
  admitsFile(candidate: string, name: string, stat: FileStat | null): boolean {
    if (!this.admits(candidate, name, false)) return false
    const size = stat?.size ?? null
    if (this.maxFilesize !== null && size !== null && size > this.maxFilesize) return false
    return this.binary || !BINARY_EXTENSIONS.has(getExtension(name) ?? '')
  }
}

/**
 * One input rg searches: its virtual path (`-` for stdin), the path rg
 * prints for it, its stat when the walk read one (the time sorts read it),
 * and the operand itself when it was named on the line, which a stream read
 * takes.
 */
export interface Haystack {
  virtual: string
  shown: string
  stat: FileStat | null
  spec: PathSpec | null
}

function errorText(err: unknown): string {
  return fsStrerror(err) ?? (err instanceof Error ? err.message : String(err))
}

/**
 * An OS error the way ripgrep's Rust `io::Error` displays it: the strerror,
 * then the Linux errno it came from (`No such file or directory (os error
 * 2)`). A failure the vocabulary cannot number keeps its words alone.
 * Mirrors Python's os_error_text.
 */
export function osErrorText(err: unknown): string {
  const text = errorText(err)
  const condition = classify(err)
  return condition === null ? text : `${text} (os error ${String(posixErrno(condition))})`
}

// ripgrep's line for a path its walker could not stat or list: the walker's
// I/O error names the path a second time (ripgrep 14.1.1). Mirrors Python's
// walk_error_line.
export function walkErrorLine(shown: string, err: unknown): string {
  return `rg: ${shown}: IO error for operation on ${shown}: ${osErrorText(err)}`
}

// ripgrep's line for a file its searcher could not open or read: the bare
// I/O error, without the walker's preamble (ripgrep 14.1.1). Mirrors
// Python's open_error_line.
export function openErrorLine(shown: string, err: unknown): string {
  return `rg: ${shown}: ${osErrorText(err)}`
}

// An entry's path without the folder mark some backends append.
function entryName(entry: string): string {
  return rstripSlash(entry)
}

function byName(a: string, b: string): number {
  const x = entryName(a)
  const y = entryName(b)
  return x < y ? -1 : x > y ? 1 : 0
}

/**
 * The files a walk of one directory operand searches, in walk order. `root`
 * is the operand's virtual path and `shownRoot` the operand as typed, which
 * every printed path below it starts with; `cwd` is the root the globs are
 * matched from. `sortByName` is --sort path, each directory's entries in
 * name order rather than the backend's. `boundary` is --one-file-system's
 * test for a mount root, which the walk does not enter, or null to enter
 * everything the backend lists. `depth` is how deep `directory` is below the
 * operand, which is listed when `directory` is null.
 */
export async function* walkHaystacks(
  readdirFn: AsyncReaddirFn,
  statFn: AsyncStatFn,
  root: string,
  shownRoot: string,
  cwd: string,
  walk: WalkFilter,
  sortByName: boolean,
  warnings: string[] | null,
  boundary: ((path: string) => boolean) | null = null,
  depth = 0,
  directory: string | null = null,
): AsyncGenerator<Haystack> {
  const here = directory ?? root
  if (walk.maxDepth !== null && depth >= walk.maxDepth) return
  let entries: string[]
  try {
    entries = await readdirFn(here)
  } catch (err) {
    if (!isWalkError(err)) throw err
    warnings?.push(walkErrorLine(respellOne(here, root, shownRoot), err))
    return
  }
  if (sortByName) entries = [...entries].sort(byName)
  for (const entry of entries) {
    // box/dropbox readdir marks folders with a trailing slash.
    const child = entryName(entry) || entry
    const shown = respellOne(child, root, shownRoot)
    let s: FileStat
    try {
      s = await statFn(entry)
    } catch (err) {
      if (!isWalkError(err)) throw err
      warnings?.push(walkErrorLine(shown, err))
      continue
    }
    const name = gnuBasename(child)
    const candidate = walkCandidate(shown, cwd)
    if (s.type === FileType.DIRECTORY) {
      if (boundary?.(child) === true) continue
      if (walk.admits(candidate, name, true)) {
        yield* walkHaystacks(
          readdirFn,
          statFn,
          root,
          shownRoot,
          cwd,
          walk,
          sortByName,
          warnings,
          boundary,
          depth + 1,
          child,
        )
      }
    } else if (s.type === FileType.FILE && walk.admitsFile(candidate, name, s)) {
      yield { virtual: child, shown, stat: s, spec: null }
    }
  }
}

/**
 * The candidates a walk of `scopes` would have searched. A search push-down
 * narrows a directory search to candidate files and hands them on as
 * operands of their own, which ripgrep never filters, so the walk's filters
 * are applied here instead, to each directory on the way down (a directory
 * the walk would not descend hides everything below it) and to the file
 * itself, and -d counts the depth below the candidate's (longest-matching)
 * scope.
 */
export function walkCandidates(
  candidates: PathSpec[],
  scopes: readonly PathSpec[],
  walk: WalkFilter,
  cwd: string,
): PathSpec[] {
  const kept: PathSpec[] = []
  for (const p of candidates) {
    let base = ''
    let raw = ''
    let best = -1
    for (const scope of scopes) {
      const root = rstripSlash(scope.virtual)
      if (root.length > best && (p.virtual === root || p.virtual.startsWith(root + '/'))) {
        base = root
        raw = scope.rawPath
        best = root.length
      }
    }
    if (best < 0 || p.virtual === base) {
      kept.push(p)
      continue
    }
    const segments = p.virtual.slice(base.length + 1).split('/')
    if (walk.maxDepth !== null && segments.length > walk.maxDepth) continue
    let admitted = true
    for (let i = 0; i < segments.length - 1; i++) {
      const below = base + '/' + segments.slice(0, i + 1).join('/')
      const shown = respellOne(below, base, raw)
      if (!walk.admits(walkCandidate(shown, cwd), segments[i] ?? '', true)) {
        admitted = false
        break
      }
    }
    const shown = respellOne(p.virtual, base, raw)
    const last = segments[segments.length - 1] ?? ''
    if (admitted && walk.admitsFile(walkCandidate(shown, cwd), last, null)) kept.push(p)
  }
  return kept
}
