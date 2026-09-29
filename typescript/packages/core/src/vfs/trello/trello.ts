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

import { BaseVFS } from '../base.ts'
import { TrelloAccessor } from '../../accessor/trello.ts'

import { TRELLO_COMMANDS } from '../../commands/builtin/trello/index.ts'
import type { RegisteredCommand } from '../../commands/config.ts'
import { HttpTrelloTransport } from '../../core/trello/client.ts'

import type { RegisteredOp } from '../../ops/registry.ts'
import { TRELLO_OPS } from '../../ops/trello/index.ts'

import { TRELLO_PROMPT, TRELLO_WRITE_PROMPT } from './prompt.ts'
import { VFSName } from '../../types.ts'

import { redactTrelloConfig, type TrelloConfig, type TrelloConfigRedacted } from './config.ts'

export interface TrelloVFSState {
  type: string
  config: TrelloConfigRedacted
}

export class TrelloVFS extends BaseVFS {
  override readonly name: string = VFSName.TRELLO
  override readonly cachesReads: boolean = true
  override readonly prompt: string = TRELLO_PROMPT
  override readonly writePrompt: string = TRELLO_WRITE_PROMPT
  readonly config: TrelloConfig
  override readonly accessor: TrelloAccessor

  constructor(config: TrelloConfig) {
    super()
    this.config = config
    const transportOpts: { apiKey: string; apiToken: string; baseUrl?: string } = {
      apiKey: config.apiKey,
      apiToken: config.apiToken,
    }
    if (config.baseUrl !== undefined) transportOpts.baseUrl = config.baseUrl
    const accessorOpts: { workspaceId?: string; boardIds?: readonly string[] } = {}
    if (config.workspaceId !== undefined) accessorOpts.workspaceId = config.workspaceId
    if (config.boardIds !== undefined) accessorOpts.boardIds = config.boardIds
    this.accessor = new TrelloAccessor(new HttpTrelloTransport(transportOpts), accessorOpts)
  }

  override commands(): readonly RegisteredCommand[] {
    return TRELLO_COMMANDS
  }

  override ops(): readonly RegisteredOp[] {
    return TRELLO_OPS
  }

  override getState(): Promise<TrelloVFSState> {
    return Promise.resolve({
      type: this.name,
      config: redactTrelloConfig(this.config),
    })
  }
}
