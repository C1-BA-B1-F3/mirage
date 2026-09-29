import { describe, expect, it, vi } from 'vitest'
import { RAMAccessor } from '../accessor/ram.ts'
import { RAM_IO } from '../commands/builtin/ram/io.ts'
import type { RegisteredOp } from '../ops/registry.ts'
import { FileStat, FileType, PathSpec } from '../types.ts'
import { VFSAdapter } from './adapter.ts'
import { BaseVFS } from './base.ts'
import { RAMVFS } from './ram/ram.ts'
import { RAMStore } from './ram/store.ts'
import { checkDriverContract, checkReadContract, DriverOps, type ReadFixture } from './testing.ts'

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

function custom(store: RAMStore, ops: RegisteredOp[] = []): BaseVFS<RAMAccessor> {
  return new BaseVFS({
    name: 'custom',
    accessor: new RAMAccessor(store),
    io: new VFSAdapter({
      read: { readdir: RAM_IO.readdir, readBytes: RAM_IO.readBytes, stat: RAM_IO.stat },
    }),
    ops,
  })
}

async function seeded(content: Uint8Array): Promise<RAMStore> {
  const store = new RAMStore()
  await RAM_IO.write?.(new RAMAccessor(store), FILE, content)
  return store
}

describe('driver conformance', () => {
  it('checks a builtin driver through its op table', async () => {
    const ram = new RAMVFS()
    await new DriverOps(ram).write(FILE, fixture.content)
    await checkDriverContract(ram, fixture)
  })

  it.each(['', 'a', 'é: hello\n'])('checks a table-built driver for %j', async (text) => {
    const content = new TextEncoder().encode(text)
    await checkDriverContract(custom(await seeded(content)), { ...fixture, content })
  })

  it('catches a read op that ignores the window', async () => {
    const wholeRead: RegisteredOp = {
      name: 'read',
      vfs: 'custom',
      filetype: null,
      write: false,
      fn: () => Promise.resolve(fixture.content),
    }
    await expect(
      checkDriverContract(custom(await seeded(fixture.content), [wholeRead]), fixture),
    ).rejects.toThrow('offset and byte count')
  })

  it('catches a stat that answers for a missing path', async () => {
    const lenientStat: RegisteredOp = {
      name: 'stat',
      vfs: 'custom',
      filetype: null,
      write: false,
      fn: (accessor, path, _args, kwargs) =>
        path.vfsPath === fixture.missing.vfsPath
          ? Promise.resolve(new FileStat({ name: 'missing', type: FileType.FILE, size: 0 }))
          : RAM_IO.stat(accessor as RAMAccessor, path, kwargs.index),
    }
    await expect(
      checkDriverContract(custom(await seeded(fixture.content), [lenientStat]), fixture),
    ).rejects.toThrow('missing paths must raise ENOENT')
  })

  it('calls a driver without a workspace', async () => {
    const table = new DriverOps(new RAMVFS())
    await table.write(FILE, new TextEncoder().encode('payload'))
    expect(new TextDecoder().decode(await table.read(FILE))).toBe('payload')
    expect(new TextDecoder().decode(await table.read(FILE, { offset: 1, size: 3 }))).toBe('ayl')
    expect(table.has('glob')).toBe(true)
    expect(() => table.op('search')).toThrow('no op registered')
  })
})
