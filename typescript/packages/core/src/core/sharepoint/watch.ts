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

import type { SharePointAccessor } from '../../accessor/sharepoint.ts'
import type { IndexCacheStore } from '../../cache/index/store.ts'
import type { FileStat, PathSpec } from '../../types.ts'
import type { DeltaHook } from '../../watch/base.ts'
import { ListingDeltaHook } from '../../watch/delta.ts'
import { ReaddirWalk } from '../../watch/walk.ts'
import { readdir } from './readdir.ts'
import { stat } from './stat.ts'

/**
 * Build the SharePoint delta hook.
 *
 * Same Graph drive surface as OneDrive, so the same `cTag` fingerprint and the
 * same standing offer of a native `/delta` fast path; see
 * `core/onedrive/watch.ts`.
 */
export function buildDeltaHook(accessor: SharePointAccessor): DeltaHook {
  const walk = new ReaddirWalk(
    (path: PathSpec, index: IndexCacheStore): Promise<string[]> => readdir(accessor, path, index),
    (path: PathSpec, index: IndexCacheStore): Promise<FileStat> => stat(accessor, path, index),
  )
  return new ListingDeltaHook(walk.walk.bind(walk))
}
