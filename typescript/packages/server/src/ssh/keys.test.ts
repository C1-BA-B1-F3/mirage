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

import { mkdtempSync, readFileSync, statSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import ssh2 from 'ssh2'
import { describe, expect, it } from 'vitest'
import { loadHostKey, mintKeyPair } from './keys.ts'

function publicOf(privateKey: string): string {
  const parsed = ssh2.utils.parseKey(privateKey)
  if (parsed instanceof Error) throw parsed
  return parsed.getPublicSSH().toString('base64')
}

describe('loadHostKey', () => {
  it('mints an owner-only ed25519 key on first use', () => {
    const path = join(mkdtempSync(join(tmpdir(), 'mirage-ssh-keys-')), 'ssh', 'host_key')
    const key = loadHostKey(path, ssh2.utils)
    const parsed = ssh2.utils.parseKey(key)
    expect(parsed instanceof Error ? parsed : parsed.type).toBe('ssh-ed25519')
    expect(statSync(path).mode & 0o777).toBe(0o600)
    expect(statSync(join(path, '..')).mode & 0o777).toBe(0o700)
  })

  it('keeps the same key across loads', () => {
    const path = join(mkdtempSync(join(tmpdir(), 'mirage-ssh-keys-')), 'host_key')
    const first = loadHostKey(path, ssh2.utils)
    expect(publicOf(loadHostKey(path, ssh2.utils))).toBe(publicOf(first))
  })

  it('reads an existing key instead of replacing it', () => {
    const path = join(mkdtempSync(join(tmpdir(), 'mirage-ssh-keys-')), 'host_key')
    const mine = mintKeyPair(ssh2.utils).private
    writeFileSync(path, mine)
    expect(loadHostKey(path, ssh2.utils)).toBe(mine)
    expect(readFileSync(path, 'utf-8')).toBe(mine)
  })
})

describe('mintKeyPair', () => {
  it('mints again when ssh2 hands back a pair it cannot read', () => {
    const pairs = [{ private: 'truncated', public: 'truncated' }]
    const utils = {
      ...ssh2.utils,
      generateKeyPairSync: () => pairs.shift() ?? ssh2.utils.generateKeyPairSync('ed25519'),
    }
    const path = join(mkdtempSync(join(tmpdir(), 'mirage-ssh-keys-')), 'host_key')
    const key = loadHostKey(path, utils)
    expect(ssh2.utils.parseKey(key)).not.toBeInstanceOf(Error)
    expect(readFileSync(path, 'utf-8')).toBe(key)
  })
})
