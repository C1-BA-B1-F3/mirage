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

import type { PathSpec } from '../../../../../types.ts'
import { cpGeneric, parseFlags } from '../../cp.ts'
import type { CrossResult, DispatchFn } from '../types.ts'
import { flatten, readBytesOp, readdirOp, statOp } from '../utils.ts'
import type { FlagValue } from '../../../../spec/types.ts'
import type { NamespaceView } from '../../../../../ops/types.ts'
import { FlagView } from '../../../../spec/flag_view.ts'
import { specOf } from '../../../../spec/builtins.ts'

// Copy operands that span mounts via the shared generic cp. Pure wiring: the
// generic runs in its primitive (no native copy) mode, reading from the
// source mount and writing to the destination mount through dispatch-relayed
// primitives.
export async function runCp(
  scopes: PathSpec[],
  flagKwargs: Record<string, FlagValue>,
  dispatch: DispatchFn,
  // Maps an operand to its storage identity so two prefixes over one
  // store compare equal.
  storageKey?: (path: PathSpec) => string,
  // The namespace's links, which a copy that does not follow them recreates
  // by name.
  ns?: NamespaceView,
  // The working directory a typed link source resolves against.
  cwd = '/',
): Promise<CrossResult> {
  const flat = flatten(scopes)
  const stat = statOp(dispatch)
  const readBytes = readBytesOp(dispatch)
  const relayed = readdirOp(dispatch)
  // cp -x: a mount root below the operands is empty, so the copy makes the
  // mount point and reads nothing on the other filesystem, as GNU's
  // --one-file-system does.
  const fl = new FlagView(flagKwargs, specOf('cp'))
  const mounts = fl.asBool('one_file_system') ? ns?.mounts : undefined
  const starts = new Set(scopes.map((s) => s.virtual))
  const readdir: typeof relayed =
    mounts === undefined
      ? relayed
      : (p) =>
          !starts.has(p.virtual) && mounts.isRoot(p.virtual) ? Promise.resolve([]) : relayed(p)
  const write = async (p: PathSpec, data: Uint8Array): Promise<void> => {
    await dispatch('write', p, [data])
  }
  const mkdir = async (p: PathSpec): Promise<void> => {
    await dispatch('mkdir', p)
  }
  const strategy = { readBytes, write, mkdir, readdir }
  return cpGeneric(
    flat,
    stat,
    strategy,
    parseFlags(fl),
    undefined,
    storageKey,
    undefined,
    undefined,
    ns?.links === undefined
      ? undefined
      : { links: ns.links, dispatch, cwd, relay: strategy, relayStat: stat },
  )
}
