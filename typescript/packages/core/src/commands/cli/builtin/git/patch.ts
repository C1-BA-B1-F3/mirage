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
import { getOpcodes, groupOpcodes } from '../../../builtin/diff_format.ts'
import { DiffOpTag } from '../../../builtin/diff_types.ts'
import { FUNCNAME_START, GIT_SPACE } from './constants.ts'
import { quotePath } from './render.ts'
import { repoArgs, type Repo } from './repo.ts'
import type { TreeEntry } from './tree.ts'

const HUNK_CONTEXT = 3
const FUNCNAME_BYTES = 80
const HUNK_HEADER_BYTES = 128
const BINARY_SNIFF = 8000
const OID_HEX = 40
const DEV_NULL = '/dev/null'
const ENC = new TextEncoder()
const DEC = new TextDecoder()

async function blobData(repo: Repo, entry: TreeEntry | null): Promise<Uint8Array> {
  if (!entry) return new Uint8Array()
  if (entry.mode === '160000') return ENC.encode(`Subproject commit ${entry.oid}\n`)
  return (await git.readBlob({ ...repoArgs(repo), oid: entry.oid })).blob
}
function lines(data: Uint8Array): string[] {
  const text = DEC.decode(data)
  return text === '' ? [] : text.split(/(?<=\n)/)
}

/** An entry's object id cut to `width`, zeros for a missing side. */
export function shortOid(entry: TreeEntry | null, width: number): string {
  return (entry?.oid ?? '0'.repeat(OID_HEX)).slice(0, width)
}

/**
 * One path's patch, headers and hunks, as git's builtin_diff writes it. A
 * change between a file and a symlink is split into a deletion and a creation,
 * the way git's run_diff splits a type change. A `---` or `+++` label holding a
 * space ends in a tab, so a patch tool can tell where the name stops.
 */
export async function filePatch(
  repo: Repo,
  path: string,
  oldPath: string,
  before: TreeEntry | null,
  after: TreeEntry | null,
  score: number | null,
  width: number,
  fully = true,
  count = HUNK_CONTEXT,
): Promise<string> {
  if (before && after && before.mode.slice(0, 3) !== after.mode.slice(0, 3))
    return (
      (await filePatch(repo, path, oldPath, before, null, score, width, fully, count)) +
      (await filePatch(repo, path, oldPath, null, after, score, width, fully, count))
    )
  const source = quotePath(`a/${oldPath}`, false, fully),
    target = quotePath(`b/${path}`, false, fully)
  const head = [`diff --git ${source} ${target}`]
  if (!before && after) head.push(`new file mode ${after.mode}`)
  else if (!after && before) head.push(`deleted file mode ${before.mode}`)
  else if (before && after && before.mode !== after.mode)
    head.push(`old mode ${before.mode}`, `new mode ${after.mode}`)
  if (score !== null)
    head.push(
      `similarity index ${String(score)}%`,
      `rename from ${quotePath(oldPath, false, fully)}`,
      `rename to ${quotePath(path, false, fully)}`,
    )
  if (before && before.oid === after?.oid) return text(head)
  head.push(
    `index ${shortOid(before, width)}..${shortOid(after, width)}` +
      (before && before.mode === after?.mode ? ` ${after.mode}` : ''),
  )
  const old = await blobData(repo, before),
    fresh = await blobData(repo, after)
  const from = before ? source : DEV_NULL,
    to = after ? target : DEV_NULL
  if ([old, fresh].some((data) => data.subarray(0, BINARY_SNIFF).includes(0)))
    return text([...head, `Binary files ${from} and ${to} differ`])
  const body = hunks(lines(old), lines(fresh), count)
  return (
    text(body ? [...head, `--- ${from}${labelTab(from)}`, `+++ ${to}${labelTab(to)}`] : head) + body
  )
}

/** The tab git puts after a `---`/`+++` label holding a space. */
function labelTab(label: string): string {
  return label.includes(' ') ? '\t' : ''
}

function text(rows: readonly string[]): string {
  return rows.map((row) => row + '\n').join('')
}

/**
 * The `@@` hunks of a two-way patch, as xdiff's xdl_emit_diff emits them. Each
 * header carries the nearest earlier line of the old side that starts with a
 * letter, `_` or `$` (git's default funcname), and keeps the previous hunk's
 * when none lies between the two.
 */
function hunks(old: readonly string[], fresh: readonly string[], count: number): string {
  const out: string[] = []
  let context = ''
  let searched = -1
  for (const group of groupOpcodes(getOpcodes(old, fresh), count)) {
    const first = group[0],
      last = group.at(-1)
    if (first === undefined || last === undefined) continue
    const start = first[1]
    for (let k = start - 1; k > searched; k--) {
      const line = old[k] ?? ''
      if (FUNCNAME_START.test(line)) {
        context = trimmed(ENC.encode(line).subarray(0, FUNCNAME_BYTES))
        break
      }
    }
    searched = start - 1
    let header = `@@ -${span(start, last[2])} +${span(first[3], last[4])} @@`
    if (context) {
      const room = HUNK_HEADER_BYTES - ENC.encode(header).length - 2
      header += ' ' + DEC.decode(ENC.encode(context).subarray(0, room))
    }
    out.push(header + '\n')
    for (const [tag, i1, i2, j1, j2] of group) {
      if (tag === DiffOpTag.EQUAL) {
        for (const line of old.slice(i1, i2)) out.push(hunkLine(' ', line))
        continue
      }
      for (const line of old.slice(i1, i2)) out.push(hunkLine('-', line))
      for (const line of fresh.slice(j1, j2)) out.push(hunkLine('+', line))
    }
  }
  return out.join('')
}

function trimmed(bytes: Uint8Array): string {
  let end = bytes.length
  while (end > 0 && GIT_SPACE.has(bytes[end - 1] ?? 0)) end--
  return DEC.decode(bytes.subarray(0, end))
}

function span(start: number, stop: number): string {
  if (stop - start === 1) return String(start + 1)
  return `${String(stop > start ? start + 1 : start)},${String(stop - start)}`
}

function hunkLine(marker: string, line: string): string {
  return line.endsWith('\n') ? marker + line : `${marker}${line}\n\\ No newline at end of file\n`
}
