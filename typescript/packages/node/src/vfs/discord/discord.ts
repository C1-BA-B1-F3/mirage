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

import { BoundVFS } from '@struktoai/mirage-core/vfs/bound'
import { DISCORD_IO } from '@struktoai/mirage-core/commands/builtin/discord/io'
import { DiscordAccessor } from '@struktoai/mirage-core/accessor/discord'
import { DISCORD_COMMANDS } from '@struktoai/mirage-core/commands/builtin/discord/index'

import type { RegisteredCommand } from '@struktoai/mirage-core/commands/config'
import { NodeDiscordTransport } from '@struktoai/mirage-core/core/discord/client'
import { redactDiscordConfig } from '@struktoai/mirage-core/core/discord/config'
import type {
  DiscordConfig,
  DiscordConfigRedacted,
} from '@struktoai/mirage-core/core/discord/config'

import { DISCORD_OPS } from '@struktoai/mirage-core/ops/discord/index'
import type { RegisteredOp } from '@struktoai/mirage-core/ops/registry'

import type { VFS } from '@struktoai/mirage-core/vfs/base'
import { DISCORD_PROMPT, DISCORD_WRITE_PROMPT } from '@struktoai/mirage-core/vfs/discord/prompt'
import { VFSName } from '@struktoai/mirage-core/types'

export interface DiscordVFSState {
  type: string
  config: DiscordConfigRedacted
}

export class DiscordVFS extends BoundVFS<DiscordAccessor> implements VFS {
  readonly kind: string = VFSName.DISCORD
  readonly cachesReads: boolean = true
  // Every listed file carries an exact size: chat.jsonl and members/*.json
  // are rendered at readdir from payloads the listing already fetched, and
  // attachments carry Discord's CDN byte count.
  readonly sizesAlwaysKnown: boolean = true
  readonly prompt: string
  readonly writePrompt: string = DISCORD_WRITE_PROMPT
  readonly config: DiscordConfig
  readonly accessor: DiscordAccessor

  constructor(config: DiscordConfig) {
    super(DISCORD_IO)
    this.config = config
    this.accessor = new DiscordAccessor(
      new NodeDiscordTransport(config.token, config.baseUrl),
      config,
    )
    this.prompt = DISCORD_PROMPT + this.accessor.timeRange.prompt()
  }

  commands(): readonly RegisteredCommand[] {
    return DISCORD_COMMANDS
  }

  ops(): readonly RegisteredOp[] {
    return DISCORD_OPS
  }

  override getState(): Promise<DiscordVFSState> {
    return Promise.resolve({
      type: this.kind,
      config: redactDiscordConfig(this.config),
    })
  }
}
