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

import { type DeltaHook, ListingDeltaHook } from '@struktoai/mirage-core/watch/index'
import type { HfBucketsAccessor } from '../../accessor/hf_buckets.ts'
import { OpendalWalk } from '../opendal/watch.ts'

/**
 * Build the delta hook of a Hugging Face bucket mount.
 *
 * One recursive tree listing per pull, fingerprinted on the Hub's ETag.
 */
export function buildDeltaHook(accessor: HfBucketsAccessor): DeltaHook {
  const walk = new OpendalWalk(accessor)
  return new ListingDeltaHook(walk.walk.bind(walk))
}
