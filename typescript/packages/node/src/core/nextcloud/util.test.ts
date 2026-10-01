import { PathSpec } from '@struktoai/mirage-core/types'
import { describe, expect, it } from 'vitest'
import { isNotFound, nextcloudKey, rawPathOf } from './util.ts'

function mounted(virtual: string, vfsPath: string): PathSpec {
  return new PathSpec({ virtual, directory: virtual, vfsPath })
}

describe('rawPathOf / nextcloudKey', () => {
  it.each([
    ['/nc/docs/a.txt', 'docs/a.txt', '/docs/a.txt', 'docs/a.txt'],
    ['/nc', '', '/', ''],
    ['/nc/', '', '/', ''],
    ['/nc/docs/', 'docs', '/docs/', 'docs/'],
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
