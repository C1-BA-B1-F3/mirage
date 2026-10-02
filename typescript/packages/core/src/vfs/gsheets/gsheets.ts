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
import { GSheetsAccessor } from '../../accessor/gsheets.ts'

import { GSHEETS_COMMANDS } from '../../commands/builtin/gsheets/index.ts'
import type { RegisteredCommand } from '../../commands/config.ts'
import { TokenManager } from '../../core/google/client.ts'

import { GSHEETS_OPS } from '../../ops/gsheets/index.ts'
import type { RegisteredOp } from '../../ops/registry.ts'

import { PROMPT, WRITE_PROMPT } from './prompt.ts'
import { VFSName } from '../../types.ts'

import { redactGSheetsConfig, type GSheetsConfig, type GSheetsConfigRedacted } from './config.ts'

export interface GSheetsVFSState {
  type: string
  config: GSheetsConfigRedacted
}

export class GSheetsVFS extends BaseVFS {
  override readonly name: string = VFSName.GSHEETS
  override readonly cachesReads: boolean = true
  override readonly indexTtl: number = 86_400
  // Reads stamp listing metadata; a fresh stat checks Drive by file ID.
  override readonly readRevalidatable: boolean = true
  override readonly prompt: string = PROMPT
  override readonly writePrompt: string = WRITE_PROMPT
  readonly config: GSheetsConfig
  override readonly accessor: GSheetsAccessor

  constructor(config: GSheetsConfig) {
    super()
    this.config = config
    const tm = new TokenManager(config)
    this.accessor = new GSheetsAccessor({ tokenManager: tm })
  }

  override commands(): readonly RegisteredCommand[] {
    return GSHEETS_COMMANDS
  }

  override ops(): readonly RegisteredOp[] {
    return GSHEETS_OPS
  }

  override getState(): Promise<GSheetsVFSState> {
    return Promise.resolve({
      type: this.name,
      config: redactGSheetsConfig(this.config),
    })
  }
}
