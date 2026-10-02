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
import { GCalAccessor } from '../../accessor/gcal.ts'
import { GCAL_COMMANDS } from '../../commands/builtin/gcal/index.ts'

import type { RegisteredCommand } from '../../commands/config.ts'

import { TokenManager } from '../../core/google/client.ts'
import { GCAL_OPS } from '../../ops/gcal/index.ts'
import type { RegisteredOp } from '../../ops/registry.ts'

import { PROMPT, WRITE_PROMPT } from './prompt.ts'
import { VFSName } from '../../types.ts'

import { redactGCalConfig, type GCalConfig, type GCalConfigRedacted } from './config.ts'

export interface GCalVFSState {
  type: string
  config: GCalConfigRedacted
}

export class GCalVFS extends BaseVFS {
  override readonly name: string = VFSName.GCAL
  override readonly cachesReads: boolean = true
  // Shorter than the other Google mounts: a calendar is edited by other
  // people and a day-long index would keep serving a schedule that has
  // already moved.
  override readonly indexTtl: number = 300
  override readonly prompt: string
  override readonly writePrompt: string = WRITE_PROMPT
  readonly config: GCalConfig
  override readonly accessor: GCalAccessor

  constructor(config: GCalConfig) {
    super()
    this.config = config
    const tm = new TokenManager(config)
    this.accessor = new GCalAccessor({ tokenManager: tm, config })
    this.prompt = PROMPT + this.accessor.timeRange.prompt()
  }

  override commands(): readonly RegisteredCommand[] {
    return GCAL_COMMANDS
  }

  override ops(): readonly RegisteredOp[] {
    return GCAL_OPS
  }

  override getState(): Promise<GCalVFSState> {
    return Promise.resolve({
      type: this.name,
      config: redactGCalConfig(this.config),
    })
  }
}
