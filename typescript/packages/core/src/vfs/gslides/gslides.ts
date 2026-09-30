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
import { GSlidesAccessor } from '../../accessor/gslides.ts'

import { GSLIDES_COMMANDS } from '../../commands/builtin/gslides/index.ts'
import type { RegisteredCommand } from '../../commands/config.ts'
import { TokenManager } from '../../core/google/client.ts'

import { GSLIDES_OPS } from '../../ops/gslides/index.ts'
import type { RegisteredOp } from '../../ops/registry.ts'

import { GSLIDES_PROMPT, GSLIDES_WRITE_PROMPT } from './prompt.ts'
import { VFSName } from '../../types.ts'

import { redactGSlidesConfig, type GSlidesConfig, type GSlidesConfigRedacted } from './config.ts'

export interface GSlidesVFSState {
  type: string
  config: GSlidesConfigRedacted
}

export class GSlidesVFS extends BaseVFS {
  override readonly name: string = VFSName.GSLIDES
  override readonly cachesReads: boolean = true
  override readonly indexTtl: number = 86_400
  // Reads stamp listing metadata; a fresh stat checks Drive by file ID.
  override readonly readRevalidatable: boolean = true
  override readonly prompt: string = GSLIDES_PROMPT
  override readonly writePrompt: string = GSLIDES_WRITE_PROMPT
  readonly config: GSlidesConfig
  override readonly accessor: GSlidesAccessor

  constructor(config: GSlidesConfig) {
    super()
    this.config = config
    const tm = new TokenManager(config)
    this.accessor = new GSlidesAccessor({ tokenManager: tm })
  }

  override commands(): readonly RegisteredCommand[] {
    return GSLIDES_COMMANDS
  }

  override ops(): readonly RegisteredOp[] {
    return GSLIDES_OPS
  }

  override getState(): Promise<GSlidesVFSState> {
    return Promise.resolve({
      type: this.name,
      config: redactGSlidesConfig(this.config),
    })
  }
}
