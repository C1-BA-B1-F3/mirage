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

import type { Mem0Accessor } from '../../accessor/mem0.ts'
import type { IndexCacheStore } from '../../cache/index/store.ts'
import type { PathSpec } from '../../types.ts'
import { makeRead } from '../hierarchy/read.ts'
import type { ScopeMatch } from '../hierarchy/scope.ts'
import { jsonBytes } from '../render/json.ts'
import { listedMemory } from './readdir.ts'
import { detectScope } from './scope.ts'

async function readMemory(
  accessor: Mem0Accessor,
  _match: ScopeMatch,
  path: PathSpec,
  index?: IndexCacheStore,
): Promise<Uint8Array> {
  return jsonBytes(await listedMemory(accessor, path, index))
}

export const read = makeRead(detectScope, { memory: readMemory })

/** Stream a memory as full JSON bytes (used by jq). */
export async function* readStream(
  accessor: Mem0Accessor,
  path: PathSpec,
  index?: IndexCacheStore,
): AsyncIterable<Uint8Array> {
  yield jsonBytes(await listedMemory(accessor, path, index))
}
