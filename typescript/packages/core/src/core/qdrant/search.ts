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

import type { QdrantAccessor } from '../../accessor/qdrant.ts'
import type { Row } from '../vector/types.ts'
import { groupName, rowStem } from './naming.ts'
import { fieldValue } from './payload.ts'
import { renderJson, renderText } from './render.ts'

/**
 * A ranked point's path below its collection, and its body: the source text
 * when the point has one, its `.json` otherwise.
 */
export function hit(accessor: QdrantAccessor, row: Row): [string[], Uint8Array] {
  const config = accessor.config
  const segments: string[] = []
  for (const column of config.groupBy) {
    const value = fieldValue(row, column)
    if (value !== null && value !== undefined) {
      segments.push(groupName(value, config.basenameFields.includes(column)))
    }
  }
  const stem = rowStem(row, config)
  const text = config.textField !== null ? fieldValue(row, config.textField) : null
  if (text !== null && text !== undefined) {
    return [[...segments, `${stem}.txt`], renderText(row, config)]
  }
  return [[...segments, `${stem}.json`], renderJson(row, config)]
}
