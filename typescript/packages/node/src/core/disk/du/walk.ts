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

import type { DiskAccessor } from '../../../accessor/disk.ts'
import { lstat, stat } from 'node:fs/promises'
import path from 'node:path'
import { readEntries } from '../utils.ts'

/** The checked start may be the mount-root alias; descendants never follow links. */
async function* fileSizes(full: string, start = true): AsyncGenerator<[string, number]> {
  let info
  try {
    info = await (start ? stat(full) : lstat(full))
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error
    return
  }
  if (info.isFile()) {
    yield [full, info.size]
  } else if (info.isDirectory()) {
    for (const entry of await readEntries(full)) {
      yield* fileSizes(path.join(full, entry.name), false)
    }
  }
}

export async function walkSizes(full: string): Promise<number> {
  let total = 0
  for await (const [, size] of fileSizes(full)) total += size
  return total
}

export async function walkAll(
  accessor: DiskAccessor,
  full: string,
  entries: [string, number][],
): Promise<number> {
  let total = 0
  for await (const [file, size] of fileSizes(full)) {
    entries.push(['/' + path.relative(accessor.root, file).split(path.sep).join('/'), size])
    total += size
  }
  return total
}
