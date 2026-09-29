import { IOResult, type ByteSource } from '../../../../../io/types.ts'
import { type PathSpec } from '../../../../../types.ts'
import type { FlagValue } from '../../../../spec/types.ts'
import { sortGeneric } from '../../sort.ts'
import type { CrossResult, DispatchFn } from '../types.ts'
import { crossOpts, flatten, fileStreamOp } from '../utils.ts'

export async function runSort(
  scopes: PathSpec[],
  bag: Record<string, FlagValue>,
  dispatch: DispatchFn,
  stdin: ByteSource | null,
): Promise<CrossResult> {
  const reads = new IOResult()
  const write = async (path: PathSpec, data: Uint8Array): Promise<void> => {
    await dispatch('write', path, [data])
    // A replacement must cache the new bytes, not its earlier input.
    Reflect.deleteProperty(reads.reads, path.virtual)
  }
  const [body, io] = (await sortGeneric(
    flatten(scopes),
    { ...crossOpts(bag), stdin },
    fileStreamOp(dispatch, reads),
    write,
  )) ?? [null, new IOResult()]
  return [body, await reads.merge(io)]
}
