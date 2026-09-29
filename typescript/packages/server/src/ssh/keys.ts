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

import {
  closeSync,
  constants,
  existsSync,
  mkdirSync,
  openSync,
  readFileSync,
  writeSync,
} from 'node:fs'
import { dirname } from 'node:path'
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

/**
 * The daemon's SSH host key (OpenSSH private-key text), minted on first
 * use and kept.
 *
 * A fresh key per start would make every client's known_hosts entry look
 * like a man-in-the-middle, so the first start writes one with owner-only
 * permissions and every later start reads it back. Two daemons racing to
 * mint it both end up reading the one that won. The format is OpenSSH's
 * own, the same file the Python daemon writes, so either daemon can serve
 * the other's key.
 */
export function loadHostKey(path: string, utils: typeof Ssh2Mod.utils): string {
  if (existsSync(path)) return readFileSync(path, 'utf-8')
  const pair = mintKeyPair(utils)
  mkdirSync(dirname(path), { recursive: true, mode: 0o700 })
  let fd: number
  try {
    fd = openSync(path, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL, 0o600)
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code === 'EEXIST') return readFileSync(path, 'utf-8')
    throw err
  }
  try {
    writeSync(fd, pair.private)
  } finally {
    closeSync(fd)
  }
  return pair.private
}
