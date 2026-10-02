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

import { canonicalize, doorStat } from '../../../../commands/builtin/generic/realpath.ts'
import { dispatchStat, dotRefusal, typedSpec } from '../../../../commands/builtin/utils/paths.ts'
import { PathSpec } from '../../../../types.ts'
import { PolicyDenied } from '../../../../policy/index.ts'
import type { DispatchFn } from '../../../../runtime/types.ts'
import type { Namespace } from '../../../mount/namespace/namespace.ts'
import type { SessionState } from '../../../session/session.ts'
import { fail, operandText, result, splitFlags } from '../shared.ts'
import { operandAbs } from './ln.ts'
import type { Result } from '../types.ts'

// Any filesystem answer other than a target: a refusal (session view or
// policy), EINVAL (not a link), ENOENT (absent, which is what a hidden
// path answers). All of them land on GNU readlink's silent exit 1, so
// this matches python's `except OSError` rather than naming errnos one
// at a time — a list would silently print a raw path the first time a
// door answered with an errno nobody had added yet.
function readlinkRefused(err: unknown): boolean {
  if (err instanceof PolicyDenied) return true
  return typeof (err as { code?: unknown }).code === 'string'
}

// Print a symlink's target, GNU readlink semantics.
//
// The three canonicalizing flags differ only in how much of the resolved
// path has to exist: -m requires nothing, -f requires every component
// but the last, and -e requires all of it. A path that falls short
// prints nothing and exits 1.
export async function handleReadlink(
  namespace: Namespace,
  dispatch: DispatchFn,
  session: SessionState,
  args: (string | PathSpec)[],
): Promise<Result> {
  const [flags, operands] = splitFlags(args, 'fenm')
  if (operands.length === 0) {
    return fail('readlink', 'readlink: missing operand\n')
  }
  // The last of -e, -f and -m wins, as in GNU readlink.
  const typed = args
    .slice(0, args.length - operands.length)
    .map(operandText)
    .join('')
  const last = typed.match(/[efm]/g)?.pop()
  const mode = last === undefined ? null : last === 'f' ? '' : last
  const follow = (v: string): string => namespace.follow(v)
  const readlink = (v: string): string | null => namespace.readlink(v)
  const lines: string[] = []
  let exitCode = 0
  for (const op of operands) {
    const absOp = operandAbs(namespace, op, session.cwd)
    const spec = typedSpec(op, session.cwd)
    // The link entry is namespace state behind the op door: session grants
    // and admission policies decide whether this session may read the
    // target at all, so a link operand clears it even under -f, -e and -m.
    // EINVAL (not a link), a refusal and a failed walk all land on GNU
    // readlink's silent exit 1.
    try {
      if (mode !== null) {
        if (namespace.isLink(absOp)) await dispatch('readlink', PathSpec.fromStrPath(absOp))
        lines.push(
          await canonicalize(spec.rawPath, session.cwd, mode, false, readlink, doorStat(dispatch)),
        )
        continue
      }
      if (
        spec.walkError !== null ||
        (await dotRefusal(dispatchStat(dispatch), spec, follow)) !== null
      ) {
        exitCode = 1
        continue
      }
      const [found] = await dispatch('readlink', PathSpec.fromStrPath(absOp))
      lines.push(found as string)
    } catch (err) {
      if (!readlinkRefused(err)) throw err
      exitCode = 1
    }
  }
  if (lines.length === 0) return result('readlink', { exitCode })
  const text = flags.has('n') ? lines.join('') : lines.map((l) => l + '\n').join('')
  return result('readlink', { out: new TextEncoder().encode(text), exitCode })
}
