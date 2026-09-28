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

import { specOf } from '../../spec/builtins.ts'
import { FlagView } from '../../spec/flag_view.ts'
import { IOResult, materialize, type ByteSource } from '../../../io/types.ts'
import type { PathSpec } from '../../../types.ts'
import { gunzipPartial } from '../../../utils/compress.ts'
import type { CommandFnResult, CommandOpts } from '../../config.ts'
import { compilePattern, resolvePattern } from '../grep_pattern.ts'
import { STDIN_OPERAND } from '../utils/constants.ts'
import { type LinkDoor, linkDoor } from '../utils/links.ts'
import { isStdin, operandLabel, stdinStream } from '../utils/stream.ts'
import type { StatFn } from './archive/walk.ts'
import { openGzipInput } from './decompress.ts'
import { decodeLine, lineOffsets, matchOffset, prefixOf } from '../grep_offsets.ts'
import { formatRecords } from '../utils/output.ts'
import { splitLines } from '../utils/lines.ts'

const ENC = new TextEncoder()

function anyLineSelected(data: Uint8Array, pattern: RegExp, invert: boolean): boolean {
  for (const line of splitLines(decodeLine(data))) {
    let hit = pattern.test(line)
    if (invert) hit = !hit
    if (hit) return true
  }
  return false
}

interface ZgrepOpts {
  invert: boolean
  count: boolean
  lineNumbers: boolean
  onlyMatching: boolean
  maxCount: number | null
  // -b: the byte offset of each line's start or, under -o, of the match
  // itself, in the field order GNU grep prints (name, line, byte).
  byteOffsets: boolean
}

function zgrepSearch(
  data: Uint8Array,
  pattern: RegExp,
  opts: ZgrepOpts,
  filename: string | null,
): [string[], boolean] {
  const lines = splitLines(decodeLine(data))
  const offsets = opts.byteOffsets ? lineOffsets(lines) : []
  const reGlobal = opts.onlyMatching
    ? new RegExp(pattern.source, pattern.flags.includes('g') ? pattern.flags : pattern.flags + 'g')
    : null
  const matched: [number, number, string][] = []
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i] ?? ''
    const start = opts.byteOffsets ? (offsets[i] ?? 0) : 0
    if (opts.onlyMatching && !opts.invert && reGlobal !== null) {
      reGlobal.lastIndex = 0
      let m: RegExpExecArray | null
      const hits: RegExpExecArray[] = []
      while ((m = reGlobal.exec(line)) !== null) {
        hits.push(m)
        if (m[0] === '') reGlobal.lastIndex += 1
      }
      if (hits.length > 0) {
        for (const h of hits) {
          matched.push([i + 1, matchOffset(start, line, h.index), h[0]])
          if (opts.maxCount !== null && matched.length >= opts.maxCount) break
        }
      }
    } else {
      let hit = pattern.test(line)
      if (opts.invert) hit = !hit
      if (hit) matched.push([i + 1, start, line])
    }
    if (opts.maxCount !== null && matched.length >= opts.maxCount) break
  }
  if (opts.count) {
    const value =
      filename !== null ? `${filename}:${String(matched.length)}` : String(matched.length)
    return [[value], matched.length > 0]
  }
  const result: string[] = []
  for (const [idx, offset, line] of matched) {
    let prefix = ''
    if (filename !== null) prefix = filename + ':'
    prefix += prefixOf(opts.lineNumbers ? idx : null, opts.byteOffsets ? offset : null)
    result.push(prefix + line)
  }
  return [result, matched.length > 0]
}

/**
 * One operand as `gzip -cdfq` hands it to zgrep's grep.
 *
 * gzip opens the name as it would under -c and -f: a missing one is retried
 * with each suffix, a link is followed, and a directory is a warning -q keeps
 * quiet, so grep reads nothing from it. A failed open is reported in gzip's
 * words and grep still reads its empty output, which is why -c counts 0
 * there and -L lists it. The input is decoded with pass-through, the bytes
 * after a member too. Answers what grep reads and whether gzip failed (exit 2
 * for zgrep); a gzip warning is not a failure. Mirrors Python's _gunzipped.
 */
async function gunzipped(
  p: PathSpec,
  source: (p: PathSpec) => AsyncIterable<Uint8Array>,
  stat: StatFn | undefined,
  door: LinkDoor | null,
): Promise<[Uint8Array, boolean, string]> {
  let failed = false
  let errors = ''
  const report = (line: string, code: number, warning: boolean): void => {
    if (warning) return
    errors += line
    failed ||= code === 1
  }
  const found = await openGzipInput(p, source, report, {
    follow: true,
    ...(stat !== undefined ? { stat } : {}),
    door,
  })
  const raw = found === null ? new Uint8Array() : await materialize(found.stream)
  const [data, failure] = await gunzipPartial(raw, true)
  if (failure !== null && failure.exitCode !== 2) {
    errors += failure.render(operandLabel(p, 'stdin'))
    failed = true
  }
  return [data, failed, errors]
}

export async function zgrepGeneric(
  paths: PathSpec[],
  texts: string[],
  opts: CommandOpts,
  stream: (p: PathSpec) => AsyncIterable<Uint8Array>,
  stat?: StatFn,
): Promise<CommandFnResult> {
  const fl = new FlagView(opts.flags, specOf('zgrep'))
  const resolution = await resolvePattern(
    'zgrep',
    texts,
    opts.flags,
    paths,
    opts.mountPrefix,
    stream,
  )
  if (resolution.error !== null) {
    return [null, new IOResult({ exitCode: 2, stderr: ENC.encode(resolution.error) })]
  }
  const neverMatch = resolution.neverMatch
  if (resolution.pattern === null) {
    return [
      null,
      new IOResult({
        exitCode: 2,
        stderr: ENC.encode('zgrep: usage: zgrep [flags] pattern [path]\n'),
      }),
    ]
  }
  const rawPattern = resolution.pattern
  // zgrep is grep over decompressed bytes, so it reads a basic expression
  // unless -E says otherwise; -G asks for the default explicitly.
  const basicRegexp = !fl.asBool('E')
  const fixedString = fl.asBool('F') && !neverMatch
  const wholeWord = fl.asBool('w')
  const ignoreCase = fl.asBool('i')
  const invert = fl.asBool('v')
  const countOnly = fl.asBool('c')
  const lineNumbers = fl.asBool('n')
  const onlyMatching = fl.asBool('o')
  const quiet = fl.asBool('q')
  const byteOffsets = fl.asBool('byte_offset')
  // -l and -L set one mode in grep, so the later one on the line wins.
  let listing: string | null = null
  for (const name of fl.typedOrder('args_l', 'files_without_match')) {
    if (fl.asBool(name)) listing = name
  }
  const filesOnly = listing === 'args_l'
  const filesWithoutMatch = listing === 'files_without_match'
  const forceH = fl.asBool('H')
  const hideH = fl.asBool('h')
  const maxCount = fl.asInt('m') ?? null
  // GNU grep 3.11 skips regex validation and selection under -m0.
  const pattern =
    maxCount === 0
      ? null
      : compilePattern(rawPattern, ignoreCase, fixedString, wholeWord, basicRegexp)

  const multi = paths.length > 1
  const showFilename = forceH || (multi && !hideH)
  let anyMatch = false
  const allResults: string[] = []

  const read = stdinStream(stream, opts.stdin)
  const door = linkDoor(opts)
  let errors = ''
  let failed = false
  for (const p of paths.length > 0 ? paths : [STDIN_OPERAND]) {
    // zgrep decompresses each operand with `gzip -cdfq -- FILE`, which
    // reports its own failures and hands grep what it decoded.
    let data: Uint8Array
    if (isStdin(p)) {
      const [decoded, failure] = await gunzipPartial(await materialize(read(p)), true)
      data = decoded
      if (failure !== null && failure.exitCode !== 2) {
        errors += failure.render(operandLabel(p, 'stdin'))
        failed = true
      }
    } else {
      const [decoded, gzipFailed, lines] = await gunzipped(p, stream, stat, door)
      data = decoded
      errors += lines
      failed ||= gzipFailed
    }
    if (pattern === null) {
      if (filesWithoutMatch) allResults.push(p.rawPath)
      continue
    }
    // zgrep hands grep a stdin operand as `-`, so -l and -L list it as `-`
    // while its lines are labelled `(standard input)` (gzip 1.13);
    // /dev/stdin is named as typed either way.
    const fname = showFilename ? operandLabel(p, '(standard input)') : null
    if (filesOnly || filesWithoutMatch) {
      // -L lists the files that selected nothing; the status still
      // follows the matching, as GNU grep's does.
      const matched = anyLineSelected(data, pattern, invert)
      if (matched === filesOnly) allResults.push(p.rawPath)
      anyMatch ||= matched
    } else {
      const [result, hadMatch] = zgrepSearch(
        data,
        pattern,
        { invert, count: countOnly, lineNumbers, onlyMatching, maxCount, byteOffsets },
        fname,
      )
      if (hadMatch) anyMatch = true
      for (const r of result) allResults.push(r)
    }
  }

  // gzip's failure is exit 2 even beside a match, -q included (zgrep 1.13
  // takes the more serious status of gzip's and grep's per file).
  const exitCode = failed ? 2 : anyMatch ? 0 : 1
  const stderr = errors === '' ? null : ENC.encode(errors)
  // Under -m0, GNU still prints -L's operands even with -q.
  if ((quiet && maxCount !== 0) || allResults.length === 0)
    return [null, new IOResult({ exitCode, stderr })]
  const result: ByteSource = formatRecords(allResults)
  return [result, new IOResult({ exitCode, stderr })]
}
