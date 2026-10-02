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

import { mkdtempSync, readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs'
import * as fs from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import ssh2 from 'ssh2'
import { describe, expect, it, vi } from 'vitest'
import { loadHostKey, mintKeyPair } from './keys.ts'

vi.mock('node:fs/promises', async (original) => {
  const real = await original<typeof fs>()
  return { ...real, link: vi.fn(real.link), writeFile: vi.fn(real.writeFile) }
})

function publicOf(privateKey: string): string {
  const parsed = ssh2.utils.parseKey(privateKey)
  if (parsed instanceof Error) throw parsed
  return parsed.getPublicSSH().toString('base64')
}

describe('loadHostKey', () => {
  it('mints an owner-only ed25519 key on first use', async () => {
    const path = join(mkdtempSync(join(tmpdir(), 'mirage-ssh-keys-')), 'ssh', 'host_key')
    const key = await loadHostKey(path, ssh2.utils)
    const parsed = ssh2.utils.parseKey(key)
    expect(parsed instanceof Error ? parsed : parsed.type).toBe('ssh-ed25519')
    expect(statSync(path).mode & 0o777).toBe(0o600)
    expect(statSync(join(path, '..')).mode & 0o777).toBe(0o700)
  })

  it('keeps the same key across loads', async () => {
    const path = join(mkdtempSync(join(tmpdir(), 'mirage-ssh-keys-')), 'host_key')
    const first = await loadHostKey(path, ssh2.utils)
    expect(publicOf(await loadHostKey(path, ssh2.utils))).toBe(publicOf(first))
  })

  it('racing loads never read a partial key', async () => {
    const dir = mkdtempSync(join(tmpdir(), 'mirage-ssh-keys-'))
    const path = join(dir, 'host_key')
    const keys = await Promise.all(Array.from({ length: 8 }, () => loadHostKey(path, ssh2.utils)))
    expect(new Set(keys.map(publicOf)).size).toBe(1)
    expect(readdirSync(dir)).toEqual(['host_key'])
  })

  it('publishes by rename where the storage has no hard links', async () => {
    const dir = mkdtempSync(join(tmpdir(), 'mirage-ssh-keys-'))
    const path = join(dir, 'host_key')
    vi.mocked(fs.link).mockRejectedValueOnce(Object.assign(new Error('EPERM'), { code: 'EPERM' }))
    const key = await loadHostKey(path, ssh2.utils)
    expect(readFileSync(path, 'utf-8')).toBe(key)
    expect(statSync(path).mode & 0o777).toBe(0o600)
    expect(readdirSync(dir)).toEqual(['host_key'])
  })

  it('leaves no key file behind when writing it fails', async () => {
    const dir = mkdtempSync(join(tmpdir(), 'mirage-ssh-keys-'))
    vi.mocked(fs.writeFile).mockImplementationOnce(async (file) => {
      writeFileSync(file as string, 'partial')
      throw Object.assign(new Error('ENOSPC'), { code: 'ENOSPC' })
    })
    await expect(loadHostKey(join(dir, 'host_key'), ssh2.utils)).rejects.toThrow('ENOSPC')
    expect(readdirSync(dir)).toEqual([])
  })

  it('reads an existing key instead of replacing it', async () => {
    const path = join(mkdtempSync(join(tmpdir(), 'mirage-ssh-keys-')), 'host_key')
    const mine = mintKeyPair(ssh2.utils).private
    writeFileSync(path, mine)
    expect(await loadHostKey(path, ssh2.utils)).toBe(mine)
    expect(readFileSync(path, 'utf-8')).toBe(mine)
  })
})

describe('mintKeyPair', () => {
  it('mints again when ssh2 hands back a pair it cannot read', async () => {
    const pairs = [{ private: 'truncated', public: 'truncated' }]
    const utils = {
      ...ssh2.utils,
      generateKeyPairSync: () => pairs.shift() ?? ssh2.utils.generateKeyPairSync('ed25519'),
    }
    const path = join(mkdtempSync(join(tmpdir(), 'mirage-ssh-keys-')), 'host_key')
    const key = await loadHostKey(path, utils)
    expect(ssh2.utils.parseKey(key)).not.toBeInstanceOf(Error)
    expect(readFileSync(path, 'utf-8')).toBe(key)
  })
})
