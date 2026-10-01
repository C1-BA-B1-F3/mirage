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

import type { Accessor } from '../../../accessor/base.ts'
import { hiddenPathsIntersect, pathRulesActive } from '../../../context/session_context.ts'
import { makeSearchBackedFind } from '../../../core/generic/find.ts'
import type { SlugTree } from '../../../core/slug_tree/tree.ts'
import { materialize, type ByteSource } from '../../../io/types.ts'
import type { PathSpec, VFSName } from '../../../types.ts'
import { mountPrefixOf } from '../../../utils/key_prefix.ts'
import { rstripSlash } from '../../../utils/slash.ts'
import type { StatOp } from '../../../vfs/types.ts'
import {
  command,
  type CommandFnResult,
  type CommandOpts,
  type RegisteredCommand,
} from '../../config.ts'
import { specOf } from '../../spec/builtins.ts'
import { FlagView } from '../../spec/flag_view.ts'
import type { FlagValue } from '../../spec/types.ts'
import { findGeneric } from '../generic/find.ts'
import {
  resolveGlobOf,
  withPathGuards,
  withPolicyGuard,
  type CommandIO,
} from '../generic_bind/adapter.ts'
import { findWalk } from '../generic_bind/builders/find.ts'

const ENC = new TextEncoder()
const DEC = new TextDecoder('utf-8', { fatal: false })

function defaultName(name: string | undefined, texts: readonly string[]): string | undefined {
  if (name !== undefined) return name
  const first = texts[0]
  if (first !== undefined && !first.startsWith('-') && !['(', ')', '!'].includes(first)) {
    return first
  }
  return undefined
}

async function normalizeFindOutput(
  stdout: ByteSource | null,
  searchPath: PathSpec,
): Promise<ByteSource | null> {
  if (stdout === null) return null
  const data = await materialize(stdout)
  const prefix = rstripSlash(mountPrefixOf(searchPath.virtual, searchPath.vfsPath))
  const root = prefix !== '' ? prefix : '/'
  const text = DEC.decode(data)
  const lines = text === '' ? [] : text.replace(/\n$/, '').split('\n')
  const normalized = lines.map((line) => (line === root + '/' ? root : line))
  if (normalized.length === 0) return new Uint8Array(0)
  return ENC.encode(normalized.join('\n') + '\n')
}

const TIME_TESTS = new Set(['-mtime', '-newer', '-newermt'])
const TIME_DIRECTIVE = /%[aAcCtTBW]/

/** Whether the expression reads a timestamp, which the light stat only approximates from the listing. */
export function readsTimes(texts: readonly string[]): boolean {
  return texts.some(
    (word, i) =>
      TIME_TESTS.has(word) || (word === '-printf' && TIME_DIRECTIVE.test(texts[i + 1] ?? '')),
  )
}

/**
 * Build `find` for a slug-tree backend, filtered over one tree walk.
 *
 * Args:
 *   vfs: the backend the command registers for.
 *   io: the backend's command IO.
 *   tree: the backend's tree.
 *   stat: the full stat, paid only when the expression reads times
 *     (-mtime, -newer, a -printf time).
 *   statLight: the index-only stat used otherwise.
 */
export function makeFind<A extends Accessor>(
  vfs: VFSName,
  io: CommandIO<A>,
  tree: SlugTree<A>,
  stat: StatOp<A>,
  statLight: StatOp<A>,
): RegisteredCommand[] {
  const resolveGlob = resolveGlobOf(io)
  const findCore = makeSearchBackedFind<A>({ resolvePath: tree.resolve, stat, walk: tree.walk })
  const walkFull = withPolicyGuard(withPathGuards(io))
  const walkLight = withPolicyGuard(withPathGuards({ ...io, stat: statLight }))
  return command({
    name: 'find',
    vfs,
    spec: specOf('find'),
    fn: async (
      accessor: A,
      paths: PathSpec[],
      texts: string[],
      opts: CommandOpts,
    ): Promise<CommandFnResult> => {
      const index = opts.index ?? undefined
      const resolved = paths.length > 0 ? await resolveGlob(accessor, paths, index) : []
      const searchPath = resolved[0]
      // Push-down choices: a bare word acts as the -name filter, and the
      // heavier per-document stat is only paid when the expression reads
      // times.
      const fl = new FlagView(opts.flags, specOf('find'))
      const bag: Record<string, FlagValue> = { ...opts.flags }
      const name = defaultName(fl.asStr('name'), texts)
      if (name !== undefined) bag.name = name
      const timed = readsTimes(texts)
      const statFn = timed ? stat : statLight
      // A tree walk classifies on the raw backend tree, so under hidden
      // paths or a path rule it would answer for entries the session cannot
      // see; the walk classifies through the guarded readdir/stat, the fork
      // the factory builder takes.
      const result =
        pathRulesActive() || resolved.some((p) => hiddenPathsIntersect(p.virtual))
          ? await findWalk(timed ? walkFull : walkLight, accessor, resolved, texts, {
              ...opts,
              flags: bag,
            })
          : await findGeneric(
              resolved,
              texts,
              { ...opts, flags: bag },
              (root, options) => findCore(accessor, root, options, index),
              (spec: PathSpec) => statFn(accessor, spec, index),
            )
      if (result === null || searchPath === undefined) return result
      const [stdout, ioResult] = result
      return [await normalizeFindOutput(stdout, searchPath), ioResult]
    },
  })
}
