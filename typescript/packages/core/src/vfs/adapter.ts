import type { Accessor } from '../accessor/base.ts'
import type { CommandIO } from '../commands/builtin/generic_bind/adapter.ts'
import { streamFromBytes } from '../commands/builtin/utils/wrap.ts'
import { isEnoent, isEnotdir } from '../utils/errors.ts'
import type { NativeReadOps, ReadOps, WriteOps, SearchOps, ReadBytesOp, WriteOp } from './types.ts'

export interface VFSAdapterOptions<A extends Accessor = Accessor> {
  read: ReadOps<A>
  native?: NativeReadOps<A>
  writes?: WriteOps<A>
  search?: SearchOps<A>
  local?: boolean
  isMounted?: CommandIO<A>['isMounted']
  maxGlobMatches?: number
  maxDuEntries?: number
}

/** Compose capabilities into one table for commands and filesystem ops. */
export class VFSAdapter<A extends Accessor = Accessor> {
  constructor(readonly options: VFSAdapterOptions<A>) {}

  toCommandIO(): CommandIO<A> {
    const { read, native, writes, ...settings } = this.options
    return {
      ...read,
      streamsBytes: native?.readStream === undefined,
      readStream: (a, p, i) => streamFromBytes(read.readBytes, a, p, i),
      exists: async (a, p) => {
        try {
          await read.stat(a, p)
          return true
        } catch (error) {
          if (isEnoent(error) || isEnotdir(error)) return false
          throw error
        }
      },
      local: false,
      isMounted: () => true,
      ...settings,
      ...native,
      ...writes,
    }
  }
}

/** Explicit non-atomic read/modify/write append for byte stores. */
export function appendFromRead<A extends Accessor>(
  read: ReadBytesOp<A>,
  write: WriteOp<A>,
): WriteOp<A> {
  return async (accessor, path, data) => {
    let previous: Uint8Array
    try {
      previous = await read(accessor, path)
    } catch (error) {
      if (!isEnoent(error)) throw error
      previous = new Uint8Array()
    }
    const merged = new Uint8Array(previous.length + data.length)
    merged.set(previous)
    merged.set(data, previous.length)
    await write(accessor, path, merged)
  }
}
