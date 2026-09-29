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

export const ENV_SSH_PORT = 'MIRAGE_SSH_PORT'
export const ENV_SSH_HOST = 'MIRAGE_SSH_HOST'
export const ENV_SSH_HOST_KEY_FILE = 'MIRAGE_SSH_HOST_KEY_FILE'
export const ENV_SSH_AUTHORIZED_KEYS = 'MIRAGE_SSH_AUTHORIZED_KEYS'

export const DEFAULT_SSH_HOST = '127.0.0.1'
export const SSH_DIR = 'ssh'
export const HOST_KEY_NAME = 'host_ed25519_key'
export const AUTHORIZED_KEYS_NAME = 'authorized_keys'

/**
 * The authorized_keys option that binds a key to one of the workspace's
 * profiles (`mirage-profile="guarded" ssh-ed25519 AAAA...`). The server
 * reads it, never the client, so a key cannot pick a looser profile.
 */
export const PROFILE_OPTION = 'mirage-profile'

export const SSH_ENV_KEYS = {
  ssh_port: ENV_SSH_PORT,
  ssh_host: ENV_SSH_HOST,
  ssh_host_key_file: ENV_SSH_HOST_KEY_FILE,
  ssh_authorized_keys: ENV_SSH_AUTHORIZED_KEYS,
} as const
