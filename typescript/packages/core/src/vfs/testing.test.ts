import { describe, expect, it, vi } from 'vitest'
import { RAMAccessor } from '../accessor/ram.ts'
import { RAM_IO } from '../commands/builtin/ram/io.ts'
import { PathSpec } from '../types.ts'
import { VFSAdapter } from './adapter.ts'
import { RAMStore } from './ram/store.ts'
import { checkReadContract, type ReadFixture } from './testing.ts'

const FILE = new PathSpec({ virtual: '/data/a.txt', directory: '/data', vfsPath: 'a.txt' })
const fixture: ReadFixture = {
  file: FILE,
  directory: new PathSpec({ virtual: '/data', directory: '/', vfsPath: '' }),
  missing: new PathSpec({ virtual: '/data/missing', directory: '/data', vfsPath: 'missing' }),
  content: new TextEncoder().encode('é: hello\n'),
}

describe('adapter conformance', () => {
  it.each([false, true])('checks builtin and minimal adapters, native=%s', async (native) => {
    const accessor = new RAMAccessor(new RAMStore())
    await RAM_IO.write?.(accessor, FILE, fixture.content)
    const adapter = native
      ? RAM_IO
      : new VFSAdapter({
          read: {
            readdir: RAM_IO.readdir,
            readBytes: RAM_IO.readBytes,
            stat: RAM_IO.stat,
          },
        })
    await checkReadContract(adapter, accessor, fixture)
  })

  it('catches a range callback treating size as end', async () => {
    const accessor = new RAMAccessor(new RAMStore())
    await RAM_IO.write?.(accessor, FILE, fixture.content)
    await expect(
      checkReadContract(
        {
          ...RAM_IO,
          readRange: (_a, _p, _i, offset, size) =>
            Promise.resolve(fixture.content.slice(offset, size ?? undefined)),
        },
        accessor,
        fixture,
      ),
    ).rejects.toThrow('offset and byte count')
  })

  it.each(['', 'a', 'ab', 'é: hello\n'])('only probes valid native ranges for %j', async (text) => {
    const content = new TextEncoder().encode(text)
    const accessor = new RAMAccessor(new RAMStore())
    await RAM_IO.write?.(accessor, FILE, content)
    const readRange = vi.fn<NonNullable<typeof RAM_IO.readRange>>((_a, _p, _i, offset, size) => {
      if (size === 0 || offset >= content.length)
        return Promise.reject(new Error('unsatisfiable native range'))
      return Promise.resolve(content.slice(offset, size === null ? undefined : offset + size))
    })
    await checkReadContract({ ...RAM_IO, readRange }, accessor, { ...fixture, content })
    expect(readRange).toHaveBeenCalledTimes(content.length > 0 ? 2 : 0)
    if (content.length > 0) {
      expect(readRange.mock.calls[0]?.[4]).not.toBeNull()
      expect(readRange.mock.calls[1]?.[4]).toBeNull()
    }
  })

  it('propagates permission failures', async () => {
    const accessor = new RAMAccessor(new RAMStore())
    await expect(
      checkReadContract(
        { ...RAM_IO, readBytes: () => Promise.reject(new Error('denied')) },
        accessor,
        fixture,
      ),
    ).rejects.toThrow('denied')
  })
})
