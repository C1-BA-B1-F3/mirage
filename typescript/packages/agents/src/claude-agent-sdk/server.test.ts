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

import { describe, expect, it } from 'vitest'
import { OpsRegistry } from '@struktoai/mirage-core/ops/registry'
import { RAMVFS } from '@struktoai/mirage-core/vfs/ram/ram'
import { MountMode } from '@struktoai/mirage-core/types'
import { Workspace } from '@struktoai/mirage-node'
import { MirageToolOperations } from '../tool-operations.ts'

function mkWs(): Workspace {
  const ram = new RAMVFS()
  const ops = new OpsRegistry()
  for (const op of ram.ops()) ops.register(op)
  return new Workspace({ '/': ram }, { mode: MountMode.WRITE, ops })
}

function firstText(r: { content: { text: string }[] }): string {
  return r.content[0]?.text ?? ''
}

describe('execute', () => {
  it('echoes', async () => {
    const result = await new MirageToolOperations(mkWs()).execute('echo hello')
    expect(firstText(result)).toContain('hello')
    expect(result.isError).not.toBe(true)
  })

  it('runs a pipe', async () => {
    const ws = mkWs()
    await ws.vfs.writeFile('/pipe.txt', 'aaa\nbbb\naaa\n')
    const result = await new MirageToolOperations(ws).execute('cat /pipe.txt | sort | uniq | wc -l')
    expect(firstText(result)).toContain('2')
  })
})

describe('read', () => {
  it('reads a file', async () => {
    const ws = mkWs()
    await ws.vfs.writeFile('/hello.txt', 'line1\nline2\nline3\n')
    const result = await new MirageToolOperations(ws).read('/hello.txt')
    expect(firstText(result)).toContain('line1')
    expect(firstText(result)).toContain('line2')
    expect(result.isError).not.toBe(true)
  })

  it('honors offset and limit', async () => {
    const ws = mkWs()
    await ws.vfs.writeFile('/multi.txt', 'a\nb\nc\nd\ne\n')
    const result = await new MirageToolOperations(ws).read('/multi.txt', 1, 2)
    const text = firstText(result)
    expect(text).toContain('b')
    expect(text).toContain('c')
    expect(text).not.toContain('a')
    expect(text).not.toContain('d')
  })

  it('errors on missing file', async () => {
    const result = await new MirageToolOperations(mkWs()).read('/nonexistent.txt')
    expect(result.isError).toBe(true)
    expect(firstText(result)).toContain('not found')
  })
})

describe('write', () => {
  it('writes a new file', async () => {
    const ws = mkWs()
    const result = await new MirageToolOperations(ws).write('/new.txt', 'hello world')
    expect(result.isError).not.toBe(true)
    expect(await ws.vfs.readFileText('/new.txt')).toBe('hello world')
  })

  it('errors when the file exists', async () => {
    const ws = mkWs()
    await ws.vfs.writeFile('/exists.txt', 'first')
    const result = await new MirageToolOperations(ws).write('/exists.txt', 'second')
    expect(result.isError).toBe(true)
    expect(firstText(result)).toContain('already exists')
  })

  it('creates parent directories', async () => {
    const ws = mkWs()
    const result = await new MirageToolOperations(ws).write('/nested/deep/file.txt', 'hi')
    expect(result.isError).not.toBe(true)
    expect(await ws.vfs.readFileText('/nested/deep/file.txt')).toBe('hi')
  })
})

describe('edit', () => {
  it('replaces a string', async () => {
    const ws = mkWs()
    await ws.vfs.writeFile('/edit.txt', 'foo bar baz')
    const result = await new MirageToolOperations(ws).edit('/edit.txt', 'bar', 'qux')
    expect(result.isError).not.toBe(true)
    expect(await ws.vfs.readFileText('/edit.txt')).toBe('foo qux baz')
  })

  it('errors on missing file', async () => {
    const result = await new MirageToolOperations(mkWs()).edit('/missing.txt', 'x', 'y')
    expect(result.isError).toBe(true)
    expect(firstText(result)).toContain('not found')
  })

  it('errors when the string is not found', async () => {
    const ws = mkWs()
    await ws.vfs.writeFile('/nostr.txt', 'hello world')
    const result = await new MirageToolOperations(ws).edit('/nostr.txt', 'xyz', 'abc')
    expect(result.isError).toBe(true)
    expect(firstText(result)).toContain('not found')
  })

  it('errors on multiple occurrences without replace_all', async () => {
    const ws = mkWs()
    await ws.vfs.writeFile('/multi.txt', 'aa bb aa')
    const result = await new MirageToolOperations(ws).edit('/multi.txt', 'aa', 'cc')
    expect(result.isError).toBe(true)
    expect(firstText(result)).toContain('replace_all')
  })

  it('replaces all occurrences', async () => {
    const ws = mkWs()
    await ws.vfs.writeFile('/all.txt', 'aa bb aa')
    const result = await new MirageToolOperations(ws).edit('/all.txt', 'aa', 'cc', true)
    expect(result.isError).not.toBe(true)
    expect(await ws.vfs.readFileText('/all.txt')).toBe('cc bb cc')
  })
})

describe('ls', () => {
  it('lists a directory', async () => {
    const ws = mkWs()
    await new MirageToolOperations(ws).write('/dir/a.txt', 'a')
    await new MirageToolOperations(ws).write('/dir/b.txt', 'b')
    const result = await new MirageToolOperations(ws).ls('/dir')
    expect(firstText(result)).toContain('a.txt')
    expect(firstText(result)).toContain('b.txt')
  })
})

describe('grep', () => {
  it('searches recursively', async () => {
    const ws = mkWs()
    await ws.vfs.writeFile('/search.txt', 'hello world\ngoodbye world\nhello again\n')
    const result = await new MirageToolOperations(ws).grep('hello', '/')
    expect(firstText(result)).toContain('hello')
  })
})
