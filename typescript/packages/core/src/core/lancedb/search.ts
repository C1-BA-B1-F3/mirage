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

import type { LanceDBAccessor } from '../../accessor/lancedb.ts'
import { PATH_SAFE } from '../hierarchy/codec.ts'
import type { Row } from '../vector/types.ts'
import { renderCard, toStr } from './render.ts'

/** A ranked row's path below its table, and its card. */
export function hit(accessor: LanceDBAccessor, row: Row): [string[], Uint8Array] {
  const config = accessor.config
  const segments: string[] = []
  for (const column of config.groupBy) {
    const value = row[column]
    if (value !== null && value !== undefined) segments.push(PATH_SAFE.encode(toStr(value)))
  }
  return [[...segments, `${toStr(row[config.idColumn])}.md`], renderCard(row, config)]
}
