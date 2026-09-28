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

import { BoundVFS } from '../bound.ts'
import { GDOCS_IO } from '../../commands/builtin/gdocs/io.ts'
import { GDocsAccessor } from '../../accessor/gdocs.ts'
import { GDOCS_COMMANDS } from '../../commands/builtin/gdocs/index.ts'

import type { RegisteredCommand } from '../../commands/config.ts'

import { TokenManager } from '../../core/google/client.ts'
import { GDOCS_OPS } from '../../ops/gdocs/index.ts'
import type { RegisteredOp } from '../../ops/registry.ts'

import type { VFS } from '../base.ts'
import { GDOCS_PROMPT, GDOCS_WRITE_PROMPT } from './prompt.ts'
import { VFSName } from '../../types.ts'

import { redactGDocsConfig, type GDocsConfig, type GDocsConfigRedacted } from './config.ts'

export interface GDocsVFSState {
  type: string
  config: GDocsConfigRedacted
}

export class GDocsVFS extends BoundVFS<GDocsAccessor> implements VFS {
  readonly kind: string = VFSName.GDOCS
  readonly cachesReads: boolean = true
  override readonly indexTtl: number = 86_400
  // Reads stamp listing metadata; a fresh stat checks Drive by file ID.
  readonly readRevalidatable: boolean = true
  readonly prompt: string = GDOCS_PROMPT
  readonly writePrompt: string = GDOCS_WRITE_PROMPT
  readonly config: GDocsConfig
  readonly accessor: GDocsAccessor

  constructor(config: GDocsConfig) {
    super(GDOCS_IO)
    this.config = config
    const tm = new TokenManager(config)
    this.accessor = new GDocsAccessor({ tokenManager: tm })
  }

  commands(): readonly RegisteredCommand[] {
    return GDOCS_COMMANDS
  }

  ops(): readonly RegisteredOp[] {
    return GDOCS_OPS
  }

  override getState(): Promise<GDocsVFSState> {
    return Promise.resolve({
      type: this.kind,
      config: redactGDocsConfig(this.config),
    })
  }
}
