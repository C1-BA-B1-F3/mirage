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

import { BaseVFS } from '@struktoai/mirage-core/vfs/base'

import type { RegisteredCommand } from '@struktoai/mirage-core/commands/config'
import type { RegisteredOp } from '@struktoai/mirage-core/ops/registry'

import { normalizeKeyPrefix } from '@struktoai/mirage-core/vfs/s3/config'
import { VFSName } from '@struktoai/mirage-core/types'
import { type DeltaHook } from '@struktoai/mirage-core/watch/index'
import { HfBucketsAccessor } from '../../accessor/hf_buckets.ts'
import { HF_BUCKETS_COMMANDS } from '../../commands/builtin/hf_buckets/index.ts'
import { buildDeltaHook } from '../../core/hf_buckets/watch.ts'
import { HF_BUCKETS_OPS } from '../../ops/hf_buckets/index.ts'
import {
  assertHfRepoId,
  type HfBucketsConfig,
  type HfBucketsConfigRedacted,
  redactHfBucketsConfig,
} from './config.ts'
import { HF_BUCKETS_PROMPT } from './prompt.ts'

export interface HfBucketsVFSState {
  type: string
  config: HfBucketsConfigRedacted
}

export class HfBucketsVFS extends BaseVFS {
  override readonly name: string = VFSName.HF_BUCKETS
  override readonly prompt: string = HF_BUCKETS_PROMPT
  override readonly cachesReads: boolean = true
  // The Hub tree API reports each file's exact byte size (the LFS
  // object size for LFS files); readdir backfills any lister-omitted
  // size with one stat.
  override readonly sizesAlwaysKnown: boolean = true
  override readonly supportsSnapshot: boolean = true
  // stat stamps the paths-info xet hash and a read stamps its download's
  // strong ETag, which is that same hash, so a `fresh` probe compares like
  // with like.
  override readonly readRevalidatable: boolean = true
  readonly config: HfBucketsConfig
  override readonly accessor: HfBucketsAccessor

  constructor(config: HfBucketsConfig) {
    super()
    assertHfRepoId(config.bucket, 'bucket')
    const normalized = normalizeKeyPrefix(config.keyPrefix)
    const cfg: HfBucketsConfig = { ...config }
    if (normalized !== undefined) {
      cfg.keyPrefix = normalized
    } else {
      delete cfg.keyPrefix
    }
    this.config = cfg
    this.accessor = new HfBucketsAccessor(this.config)
  }

  override commands(): readonly RegisteredCommand[] {
    return HF_BUCKETS_COMMANDS
  }

  override ops(): readonly RegisteredOp[] {
    return HF_BUCKETS_OPS
  }

  override deltaHook(): DeltaHook {
    return buildDeltaHook(this.accessor)
  }

  override getState(): Promise<HfBucketsVFSState> {
    return Promise.resolve({
      type: this.name,
      config: redactHfBucketsConfig(this.config),
    })
  }
}
