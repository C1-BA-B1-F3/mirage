import type { Operator } from 'opendal'
import { PathSpec } from '@struktoai/mirage-core/types'
import { describe, expect, it, vi } from 'vitest'
import { NextcloudAccessor } from '../../accessor/nextcloud.ts'
import { copy } from './copy.ts'
import { create } from './create.ts'
import { read } from './read.ts'
import { rename } from './rename.ts'
import { stream } from './stream.ts'
import { truncate } from './truncate.ts'
import { unlink } from './unlink.ts'
import { isNotFound, nextcloudKey, rawPathOf } from './util.ts'
import { write } from './write.ts'

function mounted(virtual: string, vfsPath: string): PathSpec {
  return new PathSpec({ virtual, directory: virtual, vfsPath })
}

describe('rawPathOf / nextcloudKey', () => {
  it.each([
    ['/nc/docs/a.txt', 'docs/a.txt', '/docs/a.txt', 'docs/a.txt'],
    ['/nc', '', '/', ''],
    ['/nc/', '', '/', ''],
    ['/nc/docs/', 'docs', '/docs/', 'docs/'],
    ['/nc/docs/a.txt/', 'docs/a.txt', '/docs/a.txt/', 'docs/a.txt/'],
    ['/a.txt', 'a.txt', '/a.txt', 'a.txt'],
  ])('%s (key %s) drops the mount prefix', (virtual, vfsPath, raw, key) => {
    const path = mounted(virtual, vfsPath)
    expect(rawPathOf(path)).toBe(raw)
    expect(nextcloudKey(path)).toBe(key)
  })
})

describe('isNotFound', () => {
  it("matches the binding's NotFound message prefix only", () => {
    expect(isNotFound(new Error('NotFound (permanent) at stat'))).toBe(true)
    expect(isNotFound(new Error('PermissionDenied'))).toBe(false)
    expect(isNotFound('NotFound')).toBe(false)
  })
})

function keyLog(calls: string[][]): NextcloudAccessor {
  const accessor = new NextcloudAccessor({
    url: 'https://cloud.example/remote.php/dav/files/user/',
  })
  const operator = new Proxy(
    {},
    {
      get: (_target, method) =>
        method === 'then'
          ? undefined
          : (...args: unknown[]) => {
              calls.push([String(method), ...args.filter((a) => typeof a === 'string')])
              return Promise.resolve(
                method === 'reader' ? { read: () => Promise.resolve(0n) } : Buffer.alloc(0),
              )
            },
    },
  )
  vi.spyOn(accessor, 'operator').mockResolvedValue(operator as unknown as Operator)
  return accessor
}

async function drain(chunks: AsyncIterable<Uint8Array>): Promise<void> {
  for await (const chunk of chunks) void chunk
}

const SLASHED = mounted('/nc/docs/a.txt/', 'docs/a.txt')
const OTHER = mounted('/nc/b.txt', 'b.txt')

describe('key-only ops', () => {
  it.each<[string, (accessor: NextcloudAccessor) => Promise<unknown>, string[][]]>([
    ['copy', (a) => copy(a, SLASHED, OTHER), [['copy', 'docs/a.txt/', 'b.txt']]],
    ['create', (a) => create(a, SLASHED), [['write', 'docs/a.txt/']]],
    ['read', (a) => read(a, SLASHED), [['read', 'docs/a.txt/']]],
    ['rename', (a) => rename(a, SLASHED, OTHER), [['rename', 'docs/a.txt/', 'b.txt']]],
    ['stream', (a) => drain(stream(a, SLASHED)), [['reader', 'docs/a.txt/']]],
    [
      'truncate',
      (a) => truncate(a, SLASHED, 0),
      [
        ['read', 'docs/a.txt/'],
        ['write', 'docs/a.txt/'],
      ],
    ],
    ['unlink', (a) => unlink(a, SLASHED), [['delete', 'docs/a.txt/']]],
    ['write', (a) => write(a, SLASHED, new Uint8Array([120])), [['write', 'docs/a.txt/']]],
  ])('%s keeps the typed trailing slash', async (_name, call, expected) => {
    const calls: string[][] = []
    await call(keyLog(calls))
    expect(calls).toEqual(expected)
  })
})
