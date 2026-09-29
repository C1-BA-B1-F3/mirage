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
import { LinearAccessor } from '../../accessor/linear.ts'

import { LINEAR_COMMANDS } from '../../commands/builtin/linear/index.ts'
import type { RegisteredCommand } from '../../commands/config.ts'
import { HttpLinearTransport } from '../../core/linear/client.ts'
import { redactLinearConfig } from '../../core/linear/config.ts'
import type { LinearConfig, LinearConfigRedacted } from '../../core/linear/config.ts'

import { LINEAR_OPS } from '../../ops/linear/index.ts'
import type { RegisteredOp } from '../../ops/registry.ts'

import { LINEAR_PROMPT, LINEAR_WRITE_PROMPT } from './prompt.ts'
import { VFSName } from '../../types.ts'

export interface LinearVFSState {
  type: string
  config: LinearConfigRedacted
}

export class LinearVFS extends BaseVFS {
  override readonly name: string = VFSName.LINEAR
  override readonly cachesReads: boolean = true
  // Every file is sized at its parent's readdir from the listing payload
  // (comments.jsonl via one bounded comments call), so stat always reports
  // the rendered byte length and fskit mounts serve exact reads.
  override readonly sizesAlwaysKnown: boolean = true
  override readonly prompt: string = LINEAR_PROMPT
  override readonly writePrompt: string = LINEAR_WRITE_PROMPT
  readonly config: LinearConfig
  override readonly accessor: LinearAccessor

  constructor(config: LinearConfig) {
    super()
    this.config = config
    const transportOpts: { apiKey: string; baseUrl?: string } = { apiKey: config.apiKey }
    if (config.baseUrl !== undefined) transportOpts.baseUrl = config.baseUrl
    const accessorOpts: { teamIds?: readonly string[] } = {}
    if (config.teamIds !== undefined) accessorOpts.teamIds = config.teamIds
    this.accessor = new LinearAccessor(new HttpLinearTransport(transportOpts), accessorOpts)
  }

  override commands(): readonly RegisteredCommand[] {
    return LINEAR_COMMANDS
  }

  override ops(): readonly RegisteredOp[] {
    return LINEAR_OPS
  }

  override getState(): Promise<LinearVFSState> {
    return Promise.resolve({
      type: this.name,
      config: redactLinearConfig(this.config),
    })
  }
}
