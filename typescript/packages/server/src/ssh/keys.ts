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

import { randomUUID } from 'node:crypto'
import { mkdir, readFile, rename, rm, writeFile } from 'node:fs/promises'
import { basename, dirname, join } from 'node:path'
import { DiskRecordClient } from '@struktoai/mirage-node'
import type * as Ssh2Mod from 'ssh2'

const HOST_KEY_ALGORITHM = 'ed25519'

/**
 * A fresh ed25519 key pair in OpenSSH form: `private` for a host key or a
 * client, `public` for an authorized_keys line.
 *
 * ssh2's generator strips every leading zero byte from the public key, so
 * one pair in 256 comes out a byte short and neither ssh2 nor OpenSSH can
 * read it back; such a pair is minted again.
 */
export function mintKeyPair(utils: typeof Ssh2Mod.utils): Ssh2Mod.utils.KeyPairReturn {
  for (;;) {
    const pair = utils.generateKeyPairSync(HOST_KEY_ALGORITHM)
    if (!(utils.parseKey(pair.private) instanceof Error)) return pair
  }
}

async function readHostKey(path: string): Promise<string | null> {
  try {
    return await readFile(path, 'utf-8')
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code === 'ENOENT') return null
    throw err
  }
}

async function writeHostKey(path: string, key: string): Promise<void> {
  const temp = join(dirname(path), `.${basename(path)}.${randomUUID()}`)
  try {
    await writeFile(temp, key, { mode: 0o600, flag: 'wx' })
    await rename(temp, path)
  } finally {
    await rm(temp, { force: true })
  }
}

/**
 * The daemon's SSH host key (OpenSSH private-key text), minted on first
 * use and kept.
 *
 * A fresh key per start would make every client's known_hosts entry look
 * like a man-in-the-middle, so the first start writes one with owner-only
 * permissions and every later start reads it back. Minting holds a
 * lockfile beside the key and looks again under it, so two daemons
 * starting at once agree on one key; the key is written whole and renamed
 * into place, so a reader never sees a partial file. Only exclusive create
 * and rename are needed, which every local filesystem has. A start killed
 * while minting leaves its lock, which the next start takes over once the
 * record client counts it stale. The format is OpenSSH's own, the same
 * file the Python daemon writes, so either daemon can serve the other's
 * key.
 */
export async function loadHostKey(path: string, utils: typeof Ssh2Mod.utils): Promise<string> {
  const existing = await readHostKey(path)
  if (existing !== null) return existing
  await mkdir(dirname(path), { recursive: true, mode: 0o700 })
  const records = new DiskRecordClient(dirname(path), '')
  const lock = await records.lock(basename(path))
  try {
    const minted = await readHostKey(path)
    if (minted !== null) return minted
    const key = mintKeyPair(utils).private
    await writeHostKey(path, key)
    return key
  } finally {
    await records.unlock(basename(path), lock)
  }
}
