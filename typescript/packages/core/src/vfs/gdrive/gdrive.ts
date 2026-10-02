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
import { GDriveAccessor } from '../../accessor/gdrive.ts'
import { GDRIVE_COMMANDS } from '../../commands/builtin/gdrive/index.ts'

import type { RegisteredCommand } from '../../commands/config.ts'

import { TokenManager } from '../../core/google/client.ts'
import { GDRIVE_OPS } from '../../ops/gdrive/index.ts'
import type { RegisteredOp } from '../../ops/registry.ts'

import { PROMPT } from './prompt.ts'
import { VFSName } from '../../types.ts'

import { redactGDriveConfig, type GDriveConfig, type GDriveConfigRedacted } from './config.ts'
import { buildDeltaHook } from '../../core/gdrive/watch.ts'
import { type DeltaHook } from '../../watch/index.ts'

export interface GDriveVFSState {
  type: string
  config: GDriveConfigRedacted
}

export class GDriveVFS extends BaseVFS {
  override readonly name: string = VFSName.GDRIVE
  override readonly cachesReads: boolean = true
  override readonly supportsSnapshot: boolean = true
  override readonly readRevalidatable: boolean = true
  override readonly indexTtl: number = 86_400
  override readonly prompt: string = PROMPT
  readonly config: GDriveConfig
  override readonly accessor: GDriveAccessor

  constructor(config: GDriveConfig) {
    super()
    this.config = config
    const tm = new TokenManager(config)
    this.accessor = new GDriveAccessor({ tokenManager: tm })
  }

  override commands(): readonly RegisteredCommand[] {
    return GDRIVE_COMMANDS
  }

  override ops(): readonly RegisteredOp[] {
    return GDRIVE_OPS
  }

  override deltaHook(): DeltaHook {
    return buildDeltaHook(this.accessor)
  }

  override getState(): Promise<GDriveVFSState> {
    return Promise.resolve({
      type: this.name,
      config: redactGDriveConfig(this.config),
    })
  }
}
