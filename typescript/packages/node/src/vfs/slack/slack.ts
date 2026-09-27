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
import { SLACK_IO } from '@struktoai/mirage-core/commands/builtin/slack/io'
import { SlackAccessor } from '@struktoai/mirage-core/accessor/slack'

import { SLACK_COMMANDS } from '@struktoai/mirage-core/commands/builtin/slack/index'
import type { RegisteredCommand } from '@struktoai/mirage-core/commands/config'
import { NodeSlackTransport } from '@struktoai/mirage-core/core/slack/client'
import { redactSlackConfig } from '@struktoai/mirage-core/core/slack/config'
import type { SlackConfig, SlackConfigRedacted } from '@struktoai/mirage-core/core/slack/config'

import type { RegisteredOp } from '@struktoai/mirage-core/ops/registry'
import { SLACK_OPS } from '@struktoai/mirage-core/ops/slack/index'

import type { VFS } from '@struktoai/mirage-core/vfs/base'
import { SLACK_PROMPT, SLACK_WRITE_PROMPT } from '@struktoai/mirage-core/vfs/slack/prompt'
import { VFSName } from '@struktoai/mirage-core/types'

export interface SlackVFSState {
  type: string
  config: SlackConfigRedacted
}

export class SlackVFS extends BoundVFS<SlackAccessor> implements VFS {
  readonly kind: string = VFSName.SLACK
  readonly cachesReads: boolean = true
  // Every listed file carries an exact size: chat.jsonl and users/*.json
  // are rendered at readdir from payloads the listing already fetched
  // (users.list is payload-identical to users.info, verified live), and
  // file blobs carry Slack's upload byte count.
  readonly sizesAlwaysKnown: boolean = true
  readonly prompt: string
  readonly writePrompt: string = SLACK_WRITE_PROMPT
  readonly config: SlackConfig
  readonly accessor: SlackAccessor

  constructor(config: SlackConfig) {
    super(SLACK_IO)
    this.config = config
    this.accessor = new SlackAccessor(
      new NodeSlackTransport(config.token, config.searchToken, config.baseUrl),
      config,
    )
    this.prompt = SLACK_PROMPT + this.accessor.timeRange.prompt()
  }

  commands(): readonly RegisteredCommand[] {
    return SLACK_COMMANDS
  }

  ops(): readonly RegisteredOp[] {
    return SLACK_OPS
  }

  override getState(): Promise<SlackVFSState> {
    return Promise.resolve({
      type: this.kind,
      config: redactSlackConfig(this.config),
    })
  }
}
