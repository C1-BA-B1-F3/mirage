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

import { ListingVersion } from '@struktoai/mirage-core/types'
import { BaseVFS } from '@struktoai/mirage-core/vfs/base'

import type { RegisteredCommand } from '@struktoai/mirage-core/commands/config'
import type { RegisteredOp } from '@struktoai/mirage-core/ops/registry'

import type { VFSStateBase } from '@struktoai/mirage-core/vfs/base'

import type { DeltaHook } from '@struktoai/mirage-core/watch/index'
import type { HfHubAccessor } from '../../accessor/hf_hub.ts'
import { HF_HUB_COMMANDS } from '../../commands/builtin/hf_hub/index.ts'

import { COMMIT_SHA } from '../../core/hf_hub/constants.ts'
import { buildDeltaHook } from '../../core/hf_hub/watch.ts'
import { HF_HUB_OPS } from '../../ops/hf_hub/index.ts'

/**
 * The shared body of the three Hub *repository* VFS.
 *
 * Separate from `HfBucketsVFS` (vfs/hf_buckets/hf_buckets.ts) on purpose:
 * that one drives OpenDAL against Hugging Face Buckets, which is a different
 * product -- Xet-backed mutable object storage with no commits and no
 * revisions. These three are git repositories, read through the Hub's own
 * tree API and written as commits.
 */

/**
 * The commit a revision pins every listing at, when it names one outright.
 * Only a full 40- or 64-hex string can be a commit; the Hub answers shas
 * lowercase, so the pin is lowercased to compare with what it stores. A
 * branch that happens to look like one is still safe: its listings are
 * stored at the head its revision answered, which never equals its name.
 * Each of the three VFS sets its own `listingsPin` from its accessor's
 * effective revision with this.
 */
export function hfListingsPin(revision: string): string | null {
  const lowered = revision.toLowerCase()
  return COMMIT_SHA.test(lowered) ? lowered : null
}

export abstract class HfHubVFS extends BaseVFS {
  abstract override readonly prompt: string
  abstract override readonly accessor: HfHubAccessor
  // Narrowed back to abstract: all three carry a config and so owe their own
  // redaction, and inheriting BaseVFS's bare `{type}` would drop it and read
  // back as an empty mount.
  abstract override getState(): Promise<VFSStateBase>
  override readonly cachesReads: boolean = true
  // The Hub tree reports every file's exact byte size, and for an LFS file
  // that is the object's own size rather than the pointer's, so no read can
  // be short.
  override readonly sizesAlwaysKnown: boolean = true
  override readonly supportsSnapshot: boolean = true
  override readonly readRevalidatable: boolean = true
  // One version covers every listing: the head commit the revision resolves
  // to, asked with `revision/{rev}?expand[]=sha`, and the tree is walked at
  // that commit so the rows and the version agree.
  override readonly listingVersion: ListingVersion = ListingVersion.MOUNT
  // The index is not a cache in front of a listing, it IS the listing: one
  // recursive fetch seeds it whole. A long TTL therefore spares the Hub a
  // full re-walk rather than risking a stale row.
  override readonly indexTtl: number = 86_400

  override commands(): readonly RegisteredCommand[] {
    return HF_HUB_COMMANDS
  }

  override ops(): readonly RegisteredOp[] {
    return HF_HUB_OPS
  }

  override deltaHook(): DeltaHook {
    return buildDeltaHook(this.accessor)
  }
}
