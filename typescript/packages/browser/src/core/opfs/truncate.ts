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

import { record, startOp } from '@struktoai/mirage-core/observe/context'
import { VFSName } from '@struktoai/mirage-core/types'
import type { PathSpec } from '@struktoai/mirage-core/types'
import type { OPFSAccessor } from '../../accessor/opfs.ts'
import { isNotFound, openError, resolveFileHandle, toWritableChunk } from './utils.ts'

export async function truncate(
  accessor: OPFSAccessor,
  path: PathSpec,
  length: number,
  noCreate = false,
): Promise<void> {
  const timer = startOp()
  const root = await accessor.root()
  const key = path.mountPath
  let handle: FileSystemFileHandle
  let existing: Uint8Array
  try {
    handle = await resolveFileHandle(root, key, { create: false })
    const file = await handle.getFile()
    existing = new Uint8Array(await file.arrayBuffer())
  } catch (err) {
    if (isNotFound(err)) {
      if (noCreate) return
      try {
        handle = await resolveFileHandle(root, key, { create: true })
      } catch (cerr) {
        throw await openError(root, key, cerr, path)
      }
      existing = new Uint8Array()
    } else {
      throw await openError(root, key, err, path)
    }
  }
  const out = new Uint8Array(length)
  out.set(existing.subarray(0, Math.min(existing.byteLength, length)))
  const writable = await handle.createWritable()
  await writable.write(toWritableChunk(out))
  await writable.close()
  record('truncate', path.virtual, VFSName.OPFS, 0, timer)
}
