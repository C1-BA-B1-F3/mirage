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

import { spawnSync } from 'node:child_process'
import { mkdtempSync, readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs'
import * as fs from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { DiskRecordClient } from '@struktoai/mirage-node'
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

  it('racing loads agree on one key without hard links', async () => {
    const dir = mkdtempSync(join(tmpdir(), 'mirage-ssh-keys-'))
    const path = join(dir, 'host_key')
    vi.mocked(fs.link).mockRejectedValue(Object.assign(new Error('EPERM'), { code: 'EPERM' }))
    try {
      const keys = await Promise.all(Array.from({ length: 8 }, () => loadHostKey(path, ssh2.utils)))
      expect(new Set(keys.map(publicOf)).size).toBe(1)
      expect(readFileSync(path, 'utf-8')).toBe(keys[0])
      expect(readdirSync(dir)).toEqual(['host_key'])
    } finally {
      vi.mocked(fs.link).mockReset()
    }
  })

  it('a start waiting on the lock reads the winner', async () => {
    const dir = mkdtempSync(join(tmpdir(), 'mirage-ssh-keys-'))
    const path = join(dir, 'host_key')
    const records = new DiskRecordClient(dir, '')
    const lock = await records.lock('host_key')
    const loading = loadHostKey(path, ssh2.utils)
    await new Promise((resolve) => setTimeout(resolve, 50))
    const winner = mintKeyPair(ssh2.utils).private
    writeFileSync(path, winner)
    await records.unlock('host_key', lock)
    expect(await loading).toBe(winner)
  })

  it('a lock left by a killed start does not hold up the next', async () => {
    const dir = mkdtempSync(join(tmpdir(), 'mirage-ssh-keys-'))
    const path = join(dir, 'host_key')
    const dead = spawnSync(process.execPath, ['-e', '']).pid
    writeFileSync(`${new DiskRecordClient(dir, '').recordPath('host_key')}.lock`, String(dead))
    const started = Date.now()
    const key = await loadHostKey(path, ssh2.utils)
    expect(Date.now() - started).toBeLessThan(2000)
    expect(readFileSync(path, 'utf-8')).toBe(key)
    expect(readdirSync(dir)).toEqual(['host_key'])
  })

  it('leaves no key file behind when writing it fails', async () => {
    const dir = mkdtempSync(join(tmpdir(), 'mirage-ssh-keys-'))
    vi.mocked(fs.writeFile).mockImplementationOnce((file) => {
      writeFileSync(file as string, 'partial')
      return Promise.reject(Object.assign(new Error('ENOSPC'), { code: 'ENOSPC' }))
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
