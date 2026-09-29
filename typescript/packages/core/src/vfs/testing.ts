import type { Accessor } from '../accessor/base.ts'
import type { IndexCacheStore } from '../cache/index/store.ts'
import type { CommandIO } from '../commands/builtin/generic_bind/adapter.ts'
import { FileType, type PathSpec } from '../types.ts'
import { isEnoent } from '../utils/errors.ts'
import { VFSAdapter } from './adapter.ts'

/** A small known file, its parent directory, and an absent sibling. */
export interface ReadFixture {
  file: PathSpec
  directory: PathSpec
  missing: PathSpec
  content: Uint8Array
}

function check(condition: boolean, message: string): asserts condition {
  if (!condition) throw new Error(message)
}

function sameBytes(actual: Uint8Array, expected: Uint8Array): boolean {
  return actual.length === expected.length && actual.every((byte, i) => byte === expected[i])
}

/** Verify reads against a caller-owned fixture without mutations or test dependencies.
 * Native ranges probe nonempty windows within the fixture. Empty and out-of-range
 * reads are normalized by the filesystem operation instead. */
export async function checkReadContract<A extends Accessor>(
  adapter: VFSAdapter<A> | CommandIO<A>,
  accessor: A,
  fixture: ReadFixture,
  index?: IndexCacheStore,
): Promise<void> {
  const io = adapter instanceof VFSAdapter ? adapter.toCommandIO() : adapter
  const data = await io.readBytes(accessor, fixture.file, index)
  check(sameBytes(data, fixture.content), 'readBytes differs from fixture content')
  const info = await io.stat(accessor, fixture.file, index)
  check(info.type === FileType.FILE, 'stat must classify the fixture as a file')
  check(
    info.size === null || info.size === data.length,
    'stat size must be rendered byte length or null',
  )
  const parent = await io.stat(accessor, fixture.directory, index)
  check(parent.type === FileType.DIRECTORY, 'stat must classify the parent as a directory')
  const children = await io.readdir(accessor, fixture.directory, index)
  check(children.includes(fixture.file.virtual), 'readdir must include the child virtual path')
  const chunks: number[] = []
  for await (const chunk of io.readStream(accessor, fixture.file, index)) chunks.push(...chunk)
  check(sameBytes(Uint8Array.from(chunks), data), 'readStream differs from readBytes')
  if (io.readRange !== undefined && data.length > 0) {
    const offset = Math.min(1, data.length - 1)
    for (const size of [Math.min(3, data.length - offset), undefined]) {
      const actual = await io.readRange(accessor, fixture.file, index, offset, size ?? null)
      check(
        sameBytes(actual, data.slice(offset, size === undefined ? undefined : offset + size)),
        'readRange must use offset and byte count',
      )
    }
  }
  if (io.exists !== undefined) {
    check(await io.exists(accessor, fixture.file), 'exists rejected the fixture file')
    check(!(await io.exists(accessor, fixture.missing)), 'exists accepted a missing file')
  }
  for (const operation of [io.stat, io.readBytes]) {
    try {
      await operation(accessor, fixture.missing, index)
    } catch (error) {
      if (isEnoent(error)) continue
      throw error
    }
    throw new Error('missing paths must raise ENOENT')
  }
}
