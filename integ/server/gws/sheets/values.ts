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

import type { JsonValue, Reply } from '../../kit/typescript/index.ts'
import { touchNative } from '../drive/item.ts'
import type { GwsState } from '../store/state.ts'
import { asGrid, asObj, asStr } from '../wire/json.ts'
import type { JsonObj } from '../wire/json.ts'
import { NOT_FOUND, googleError, ok } from '../wire/reply.ts'
import { parseA1, rangeLabel, rangeLabelFor } from './a1.ts'
import { clearRange, rangeValues, writeValues } from './grid.ts'

export function unparseable(rangeStr: string): Reply {
  return googleError(400, `Unable to parse range: ${rangeStr}`, 'INVALID_ARGUMENT')
}

export function batchGetValues(
  st: GwsState,
  id: string,
  ranges: string[],
  render = 'FORMATTED_VALUE',
): Reply {
  const sheet = st.sheets.get(id)
  if (sheet === undefined) return NOT_FOUND
  const valueRanges: JsonValue[] = []
  for (const rangeStr of ranges) {
    const range = parseA1(sheet, rangeStr)
    if (range === null) return unparseable(rangeStr)
    valueRanges.push({
      range: rangeLabelFor(range, rangeStr),
      majorDimension: 'ROWS',
      values: rangeValues(range, sheet.tabs, render),
    })
  }
  return ok({ spreadsheetId: id, valueRanges })
}

// totalUpdatedRows/Columns count the distinct rows and columns holding at
// least one updated cell, not the sum over the data entries, so two ranges
// overlapping one row report that row once.
export function batchUpdateValues(
  st: GwsState,
  id: string,
  data: JsonObj[],
  option = 'USER_ENTERED',
): Reply {
  const sheet = st.sheets.get(id)
  if (sheet === undefined) return NOT_FOUND
  const responses: JsonValue[] = []
  const rows = new Set<string>()
  const columns = new Set<string>()
  const tabs = new Set<number>()
  let totalCells = 0
  for (const entry of data) {
    const rangeStr = asStr(entry.range) ?? ''
    const range = parseA1(sheet, rangeStr)
    if (range === null) return unparseable(rangeStr)
    const values = asGrid(entry.values)
    const cells = writeValues(range, values, range.startRow, option)
    for (let i = 0; i < values.length; i += 1) {
      const row = values[i] as JsonValue[]
      if (row.length > 0) rows.add(`${String(range.tab.sheetId)},${String(range.startRow + i)}`)
      for (let j = 0; j < row.length; j += 1) {
        columns.add(`${String(range.tab.sheetId)},${String(range.startCol + j)}`)
      }
    }
    tabs.add(range.tab.sheetId)
    totalCells += cells
    responses.push({
      spreadsheetId: id,
      updatedRange: rangeLabel(range.tab, range.startRow, range.startCol, values),
      updatedRows: values.length,
      updatedColumns: values.length > 0 ? Math.max(...values.map((r) => r.length)) : 0,
      updatedCells: cells,
    })
  }
  touchNative(st, id)
  return ok({
    spreadsheetId: id,
    totalUpdatedRows: rows.size,
    totalUpdatedColumns: columns.size,
    totalUpdatedCells: totalCells,
    totalUpdatedSheets: tabs.size,
    responses,
  })
}

export function batchClearValues(st: GwsState, id: string, ranges: string[]): Reply {
  const sheet = st.sheets.get(id)
  if (sheet === undefined) return NOT_FOUND
  const clearedRanges: string[] = []
  for (const rangeStr of ranges) {
    const range = parseA1(sheet, rangeStr)
    if (range === null) return unparseable(rangeStr)
    clearRange(range)
    clearedRanges.push(rangeLabelFor(range, rangeStr))
  }
  touchNative(st, id)
  return ok({ spreadsheetId: id, clearedRanges })
}

export function valuesData(body: JsonObj): JsonObj[] {
  return Array.isArray(body.data) ? body.data.map(asObj) : []
}
