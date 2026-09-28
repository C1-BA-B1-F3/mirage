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
import { IOResult, type ByteSource } from '../../../io/types.ts'
import { PathSpec, type StatFn } from '../../../types.ts'
import type { CommandFnResult, CommandOpts } from '../../config.ts'
import { enoent, enotdir, fsErrorLine, isMissingPath, walkRefusal } from '../../../utils/errors.ts'
import { absentDestStrerror, dotRefusal, linkFollow, statOrEnoent } from '../utils/paths.ts'
import { rstripSlash } from '../../../utils/slash.ts'

const ENC = new TextEncoder()

function normalize(p: string, cwd: string): string {
  const path = p.startsWith('/') ? p : `${rstripSlash(cwd)}/${p}`
  const parts = path.split('/').filter((s) => s !== '' && s !== '.')
  const out: string[] = []
  for (const part of parts) {
    if (part === '..') out.pop()
    else out.push(part)
  }
  return '/' + out.join('/')
}

async function pathExists(stat: (p: PathSpec) => Promise<unknown>, p: PathSpec): Promise<boolean> {
  try {
    await stat(p)
    return true
  } catch (err) {
    if (isMissingPath(err)) return false
    throw err
  }
}

// Why one operand does not resolve under the requested mode. GNU's three
// modes ask for different amounts of the path: -m for nothing, the default
// for every component but the last, -e for all of it. A `.` or `..`
// resolves against the directory in front of it, so outside -m the dots
// walk first. Mirrors Python's _unresolved.
async function unresolved(
  p: PathSpec,
  stat: (p: PathSpec) => Promise<unknown>,
  walk: StatFn | null,
  follow: ((path: string) => string) | null,
  mustExist: boolean,
  allowMissing: boolean,
): Promise<Error | null> {
  // The walk refused the operand before realpath ran. The empty name is
  // refused in every mode, -m included, and a link loop outside -m only:
  // -m leaves the loop unresolved and prints the path as spelled
  // (coreutils 9.7).
  if (p.walkError === 'ENOENT' || (p.walkError !== null && !allowMissing)) return walkRefusal(p)
  if (allowMissing) return null
  if (walk !== null) {
    const refusal = await dotRefusal(walk, p, follow)
    if (refusal !== null) return refusal
  }
  if (mustExist) return (await pathExists(stat, p)) ? null : enoent(p)
  if (walk === null) return null
  const why = await absentDestStrerror(walk, PathSpec.fromStrPath(p.virtual))
  if (why === null) return null
  return why === 'Not a directory' ? enotdir(p) : enoent(p)
}

// Print each operand's canonical path, GNU `realpath`. An operand that does
// not resolve is reported and the rest still print, exit 1 (coreutils 9.7).
export async function realpathGeneric(
  paths: PathSpec[],
  texts: string[],
  opts: CommandOpts,
  stat: (p: PathSpec) => Promise<unknown>,
): Promise<CommandFnResult> {
  const fl = new FlagView(opts.flags, specOf('realpath'))
  const mustExist = fl.asBool('e')
  const allowMissing = fl.asBool('m')
  const walk = opts.statPath !== undefined ? statOrEnoent(opts.statPath) : null
  const follow = linkFollow(opts.ns?.links)
  const lines: string[] = []
  const errors: string[] = []
  if (paths.length > 0) {
    for (const p of paths) {
      const failure = await unresolved(p, stat, walk, follow, mustExist, allowMissing)
      if (failure !== null) {
        errors.push(fsErrorLine('realpath', p, failure))
        continue
      }
      lines.push(normalize(p.virtual, opts.cwd))
    }
  } else {
    for (const t of texts) lines.push(normalize(t, opts.cwd))
  }
  const out: ByteSource | null = lines.length > 0 ? ENC.encode(lines.join('\n') + '\n') : null
  const stderr = errors.length > 0 ? ENC.encode(errors.join('')) : null
  return [out, new IOResult({ stderr, exitCode: errors.length > 0 ? 1 : 0 })]
}
