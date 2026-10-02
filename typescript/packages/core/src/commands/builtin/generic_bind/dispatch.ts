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

import { chunks } from '../../../io/cooperative.ts'
import { NOOPAccessor } from '../../../accessor/base.ts'
import { materialize, IOResult } from '../../../io/types.ts'
import type { ByteSource } from '../../../io/types.ts'
import type { FileStat } from '../../../types.ts'
import { PathSpec } from '../../../types.ts'
import type { DispatchFn } from '../../../runtime/types.ts'
import type { NamespaceView } from '../../../ops/types.ts'
import { stripSlash } from '../../../utils/slash.ts'
import type { FlagValue } from '../../spec/types.ts'
import type { Builder, CommandIO } from './adapter.ts'

/** Use the workspace's policy-checked operations as a generic read adapter. */
export function dispatchIO(dispatch: DispatchFn): CommandIO {
  return {
    readdir: async (_accessor, path) => (await dispatch('readdir', path))[0] as string[],
    stat: async (_accessor, path) =>
      (await dispatch('stat', path, [], { nofollow: true }))[0] as FileStat,
    readBytes: async (_accessor, path) =>
      await materialize((await dispatch('read', path))[0] as ByteSource),
    readStream: async function* (_accessor, path) {
      yield* chunks((await dispatch('read', path))[0] as ByteSource)
    },
    isMounted: () => true,
  }
}

/** Run the existing builder once over the full virtual namespace. Mirrors
 * Python's run_dispatch; the mount table is dropped from `ns`, since the
 * dispatcher crosses mounts itself. The output is read before this returns,
 * inside the running command: a `fresh` mount trusts only the listings that
 * command made, so a lazy stream read after it ends would be served the
 * previous command's. */
export async function runDispatch(
  builder: Builder,
  paths: readonly PathSpec[],
  texts: readonly string[],
  bag: Record<string, FlagValue>,
  dispatch: DispatchFn,
  cwd: string,
  ns?: NamespaceView,
  stdin: ByteSource | null = null,
  signal?: AbortSignal,
): Promise<[ByteSource | null, IOResult]> {
  const view = ns === undefined ? undefined : { ...ns }
  if (view !== undefined) delete view.mounts
  const result = await builder.fn(
    dispatchIO(dispatch),
    new NOOPAccessor(),
    paths.map(
      (p) =>
        new PathSpec({
          virtual: p.virtual,
          directory: p.directory,
          vfsPath: stripSlash(p.virtual),
          pattern: p.pattern,
          resolved: p.resolved,
          rawPath: p.rawPath,
          dotted: p.dotted,
          walkError: p.walkError,
        }),
    ),
    [...texts],
    {
      stdin,
      flags: bag,
      filetypeFns: null,
      mountPrefix: '',
      cwd,
      dispatch,
      ...(signal === undefined ? {} : { signal }),
      ...(view === undefined ? {} : { ns: view }),
    },
  )
  if (result === null) return [null, new IOResult()]
  return [await materialize(result[0]), result[1]]
}
