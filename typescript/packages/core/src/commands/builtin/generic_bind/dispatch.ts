import { chunks } from '../../../io/cooperative.ts'
import { NOOPAccessor } from '../../../accessor/base.ts'
import { materialize, IOResult } from '../../../io/types.ts'
import type { ByteSource } from '../../../io/types.ts'
import type { FileStat } from '../../../types.ts'
import { PathSpec } from '../../../types.ts'
import type { DispatchFn } from '../../../runtime/types.ts'
import type { CommandOpts } from '../../config.ts'
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

/** Run the existing builder once over the full virtual namespace. */
export async function runDispatch(
  builder: Builder,
  paths: PathSpec[],
  texts: string[],
  opts: CommandOpts,
  dispatch: DispatchFn,
): Promise<[ByteSource | null, IOResult]> {
  const ns = opts.ns === undefined ? undefined : { ...opts.ns }
  if (ns !== undefined) delete ns.mounts
  const result = await builder.fn(
    dispatchIO(dispatch),
    new NOOPAccessor(),
    paths.map((p) => new PathSpec({ ...p, vfsPath: p.virtual.replace(/^\//, '') })),
    texts,
    { ...opts, ...(ns === undefined ? {} : { ns }) },
  )
  return result ?? [null, new IOResult()]
}
