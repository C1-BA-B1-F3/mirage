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
import { fsStrerror, isFsError } from '../../../utils/errors.ts'
import { mountKey } from '../../../utils/key_prefix.ts'
import { resolvePath } from '../../../utils/path.ts'
import { IOResult, materialize, type ByteSource } from '../../../io/types.ts'
import { PathSpec } from '../../../types.ts'
import type { CommandFnResult, CommandOpts } from '../../config.ts'
import { readStdinAsync } from '../utils/stream.ts'
import { splitLines } from '../utils/lines.ts'

const ENC = new TextEncoder()
const DEC = new TextDecoder('utf-8', { fatal: false })

function splitByPatterns(
  lines: readonly string[],
  patterns: readonly string[],
  suppressMatched: boolean,
): string[][] {
  const parts: string[][] = []
  let currentStart = 0
  for (const pat of patterns) {
    if (pat.startsWith('/') && pat.endsWith('/')) {
      const regex = new RegExp(pat.slice(1, -1))
      for (let idx = currentStart; idx < lines.length; idx++) {
        if (regex.test(lines[idx] ?? '')) {
          parts.push(lines.slice(currentStart, idx))
          currentStart = suppressMatched ? idx + 1 : idx
          break
        }
      }
    } else {
      const lineNum = Number.parseInt(pat, 10)
      const splitAt = lineNum - 1
      if (splitAt > currentStart) {
        parts.push(lines.slice(currentStart, splitAt))
        currentStart = splitAt
      }
    }
  }
  if (currentStart < lines.length) {
    parts.push(lines.slice(currentStart))
  }
  return parts
}

function padNum(n: number, digits: number): string {
  const s = String(n)
  return s.length >= digits ? s : '0'.repeat(digits - s.length) + s
}

function formatSuffix(index: number, digits: number, format: string | null): string {
  if (format === null) return padNum(index, digits)
  return format.replace(/%0?(\d*)([doxX])/, (_match, widthRaw: string, kind: string) => {
    const width = widthRaw === '' ? 0 : Number.parseInt(widthRaw, 10)
    const radix = kind === 'o' ? 8 : kind === 'x' || kind === 'X' ? 16 : 10
    let value = index.toString(radix)
    if (kind === 'X') value = value.toUpperCase()
    return value.padStart(width, '0')
  })
}

export async function csplitGeneric(
  paths: PathSpec[],
  texts: string[],
  opts: CommandOpts,
  stream: (p: PathSpec) => AsyncIterable<Uint8Array>,
  write: (p: PathSpec, data: Uint8Array) => Promise<void>,
  relay = false,
): Promise<CommandFnResult> {
  const fl = new FlagView(opts.flags, specOf('csplit'))
  // An output is the -f prefix, or `xx` in the working directory, plus its
  // suffix, wherever the input lives: GNU writes `xx00` to the cwd, names it
  // as it formed it (`csplit: xx00`), and stops at the first one it cannot
  // create, -k or not. Mirrors csplit.py.
  const prefixSpec = fl.asPaths('prefix')[0]
  const prefixWord = fl.asStr('prefix') ?? 'xx'
  const prefixVirtual = prefixSpec?.virtual ?? resolvePath(prefixWord, opts.cwd)
  const typedPrefix = prefixSpec?.rawPath ?? prefixWord
  const mountPrefix = opts.mountPrefix ?? ''
  const digitsValue = fl.asStr('digits')
  const suffixValue = fl.asStr('suffix_format')
  const digits = typeof digitsValue === 'string' ? Number.parseInt(digitsValue, 10) : 2
  const suffixFormat = typeof suffixValue === 'string' ? suffixValue : null
  const quiet = fl.asBool('quiet') || fl.asBool('silent')
  const keep = fl.asBool('keep_files')
  const suppressMatched = fl.asBool('suppress_matched')
  const elideEmpty = fl.asBool('elide_empty_files')
  let raw: Uint8Array
  // `-` is stdin. /dev/stdin would run csplit on the /dev mount, which is
  // where its pieces would land, so it stays a path.
  const first = paths[0]
  if (first !== undefined && first.rawPath !== '-') {
    raw = await materialize(stream(first))
  } else {
    const stdinData = await readStdinAsync(opts.stdin)
    raw = stdinData ?? new Uint8Array(0)
  }
  const text = DEC.decode(raw)
  const lines = splitLines(text)
  const parts = splitByPatterns(lines, texts, suppressMatched)
  const writes: Record<string, Uint8Array> = {}
  const sizes: string[] = []
  let stderr: Uint8Array | null = null
  try {
    for (let idx = 0; idx < parts.length; idx++) {
      const part = parts[idx] ?? []
      if (elideEmpty && part.length === 0) continue
      const name = formatSuffix(idx, digits, suffixFormat)
      const virtual = prefixVirtual + name
      const spec = PathSpec.fromStrPath(virtual, mountKey(virtual, mountPrefix))
      const data = part.length > 0 ? ENC.encode(part.join('\n') + '\n') : new Uint8Array(0)
      try {
        await write(spec, data)
      } catch (err) {
        if (!isFsError(err)) throw err
        stderr = ENC.encode(`csplit: ${typedPrefix + name}: ${String(fsStrerror(err))}\n`)
        break
      }
      // Relay writes land on whichever mount owns each path and invalidate
      // through the dispatcher; keying them here would have the runner
      // prefix them onto this mount.
      if (!relay) writes[spec.mountPath] = data
      sizes.push(String(data.byteLength))
    }
  } catch (err) {
    if (!keep) throw err
  }
  const output = quiet || sizes.length === 0 ? '' : sizes.join('\n') + '\n'
  const result: ByteSource = ENC.encode(output)
  return [result, new IOResult({ writes, ...(stderr !== null ? { stderr, exitCode: 1 } : {}) })]
}
