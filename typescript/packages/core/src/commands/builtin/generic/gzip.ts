import { decompressInputs } from './decompress.ts'
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
import { fsStrerror, isEisdir, isFsError } from '../../../utils/errors.ts'
import { pathExists } from '../utils/copy.ts'
import type { StatFn } from './archive/walk.ts'
import { mountedPath } from '../../../utils/key_prefix.ts'
import { IOResult, materialize, type ByteSource } from '../../../io/types.ts'
import type { PathSpec } from '../../../types.ts'
import { gzip } from '../../../utils/compress.ts'
import type { CommandFnResult, CommandOpts } from '../../config.ts'
import { resolveSource, stdinStream } from '../utils/stream.ts'

function concat(chunks: Uint8Array[]): Uint8Array {
  let total = 0
  for (const c of chunks) total += c.byteLength
  const out = new Uint8Array(total)
  let offset = 0
  for (const c of chunks) {
    out.set(c, offset)
    offset += c.byteLength
  }
  return out
}

export async function gzipGeneric(
  paths: PathSpec[],
  opts: CommandOpts,
  stream: (p: PathSpec) => AsyncIterable<Uint8Array>,
  write: (p: PathSpec, data: Uint8Array) => Promise<void>,
  unlink: (p: PathSpec) => Promise<void>,
  stat?: StatFn,
): Promise<CommandFnResult> {
  const fl = new FlagView(opts.flags, specOf('gzip'))
  const decompress = fl.asBool('d')
  const keep = fl.asBool('k')
  const force = fl.asBool('f')
  const stdoutMode = fl.asBool('c')

  if (decompress)
    return decompressInputs(paths, stream, {
      command: 'gzip',
      stdin: opts.stdin,
      keep,
      toStdout: stdoutMode,
      write,
      unlink,
    })
  if (paths.length === 0) {
    const result: ByteSource = await gzip(await materialize(resolveSource(opts.stdin)))
    return [result, new IOResult()]
  }
  const read = stdinStream(stream, opts.stdin)
  const writes: Record<string, Uint8Array> = {}
  const stdout: Uint8Array[] = []
  const lines: string[] = []
  let exitCode = 0
  for (const p of paths) {
    const inPlace = !(stdoutMode || p.rawPath === '-')
    // An input gzip cannot read is reported and skipped, and the run goes on
    // to the next operand (a directory is a warning, exit 2, in the house
    // `<cmd>: <path>: Is a directory` words); so is an output already there
    // without -f, and a replace -f is refused. An output it cannot create is
    // fatal: gzip's write_error leads with a newline and exits, leaving later
    // operands untouched. Pinned against gzip 1.13 (debian:stable-slim).
    // Mirrors gzip.py.
    let raw: Uint8Array
    try {
      raw = await materialize(inPlace ? stream(p) : read(p))
    } catch (err) {
      if (isEisdir(err)) {
        lines.push(`gzip: ${p.rawPath}: ${String(fsStrerror(err))}`)
        if (exitCode === 0) exitCode = 2
        continue
      }
      if (!isFsError(err)) throw err
      lines.push(`gzip: ${p.rawPath}: ${String(fsStrerror(err))}`)
      exitCode = 1
      continue
    }
    const data = await gzip(raw)
    if (!inPlace) {
      stdout.push(data)
      continue
    }
    const outPath = p.mountPath + '.gz'
    const out = mountedPath(p, outPath)
    const existed = stat !== undefined && (await pathExists(stat, out))
    if (existed && !force) {
      lines.push(`gzip: ${p.rawPath}.gz already exists;\tnot overwritten`)
      if (exitCode === 0) exitCode = 2
      continue
    }
    try {
      await write(out, data)
    } catch (err) {
      if (!isFsError(err)) throw err
      lines.push(`${existed ? '' : '\n'}gzip: ${p.rawPath}.gz: ${String(fsStrerror(err))}`)
      exitCode = 1
      if (existed) continue
      break
    }
    writes[outPath] = data
    if (!keep) await unlink(p)
  }
  const stderr = lines.length > 0 ? new TextEncoder().encode(lines.join('\n') + '\n') : null
  return [
    stdout.length > 0 ? concat(stdout) : null,
    new IOResult({ writes, exitCode, ...(stderr !== null ? { stderr } : {}) }),
  ]
}
