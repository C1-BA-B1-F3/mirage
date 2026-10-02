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

import type { Workspace } from '../workspace/workspace.ts'
import { writeFileBytes } from './fs.ts'
import { splitManifestAndBlobs } from './manifest.ts'
import { toStateDict } from './state.ts'
import { writeSnapshotTar } from './tar_io.ts'

export async function snapshot(ws: Workspace, target: string): Promise<number> {
  const state = await toStateDict(ws)
  const [manifest, blobs] = splitManifestAndBlobs(state as unknown as Record<string, unknown>)
  const tar = await writeSnapshotTar(manifest, blobs)
  await writeFileBytes(target, tar)
  return tar.byteLength
}
