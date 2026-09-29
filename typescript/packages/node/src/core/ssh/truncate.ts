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

import { enotsup } from '@struktoai/mirage-core/utils/errors'
import type { PathSpec } from '@struktoai/mirage-core/types'
import type { SSHAccessor } from '../../accessor/ssh.ts'
import { read } from './read.ts'
import { writeBytes } from './write.ts'

export async function truncate(
  accessor: SSHAccessor,
  p: PathSpec,
  length: number,
  noCreate = false,
): Promise<void> {
  if (noCreate) throw enotsup('ssh', 'truncate --no-create', p)
  let data: Uint8Array
  try {
    data = await read(accessor, p)
  } catch (err) {
    if ((err as { code?: string }).code === 'ENOENT') {
      data = new Uint8Array(0)
    } else {
      throw err
    }
  }
  const out = new Uint8Array(length)
  out.set(data.subarray(0, Math.min(data.byteLength, length)))
  await writeBytes(accessor, p, out)
}
