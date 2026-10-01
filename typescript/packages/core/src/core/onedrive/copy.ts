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

import type { OneDriveAccessor } from '../../accessor/onedrive.ts'
import { invalidateSubtree } from '../../cache/context.ts'
import type { PathSpec } from '../../types.ts'
import { copyTree } from '../msgraph/drive.ts'
import { driveLoc } from './client.ts'

/**
 * Copy a file or folder server-side.
 *
 * The whole destination subtree is invalidated here, under its own path:
 * a folder copy that merges into an existing folder changes listings below
 * `dst`, and only the op knows the mount-absolute spelling of `dst`. A
 * failed copy invalidates too, since a merge may have landed some children
 * before one failed.
 *
 * Args:
 *   accessor: OneDrive accessor.
 *   src: the item to copy.
 *   dst: where the copy lands.
 */
export async function copy(
  accessor: OneDriveAccessor,
  src: PathSpec,
  dst: PathSpec,
): Promise<void> {
  const config = accessor.config
  try {
    await copyTree(config, driveLoc(config, src.vfsPath), driveLoc(config, dst.vfsPath))
  } finally {
    await invalidateSubtree(dst)
  }
}
