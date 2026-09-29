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

import type { JsonValue } from '../../kit/typescript/index.ts'
import type { SheetTab } from '../store/types.ts'
import { asObj } from '../wire/json.ts'
import type { JsonObj } from '../wire/json.ts'
import type { A1Range } from './a1.ts'
import { FormulaEvaluator } from './formula.ts'
import { enteredValue, formattedValue, inputValue } from './value.ts'

// The grid a new spreadsheet gets, and the pixel sizes the live API
// reports for its untouched rows and columns.
export const GRID_ROWS = 1000
export const GRID_COLUMNS = 26
export const ROW_PIXELS = 21
export const COLUMN_PIXELS = 100

export function newTab(
  sheetId: number,
  title: string,
  rows = GRID_ROWS,
  cols = GRID_COLUMNS,
): SheetTab {
  return {
    sheetId,
    title,
    cells: new Map(),
    props: new Map(),
    rows,
    cols,
    rowMeta: {},
    columnMeta: {},
    bandedRanges: [],
    basicFilter: null,
    conditionalFormats: [],
  }
}

// A tab carried whole to a new id and title: values, formats, row and
// column properties, banding, the filter and conditional formats. Banded
// range ids are unique across a spreadsheet, so the copy's are minted anew
// above `bandFloor`.
export function copyTab(
  tab: SheetTab,
  sheetId: number,
  title: string,
  bandFloor: number,
): SheetTab {
  const copy = structuredClone(tab)
  copy.sheetId = sheetId
  copy.title = title
  copy.bandedRanges.forEach((banded, i) => {
    banded.bandedRangeId = bandFloor + i + 1
  })
  return copy
}

export function tabExtent(tab: SheetTab): { rows: number; cols: number } {
  let rows = 0
  let cols = 0
  for (const key of tab.cells.keys()) {
    const [r, c] = key.split(',').map(Number) as [number, number]
    rows = Math.max(rows, r + 1)
    cols = Math.max(cols, c + 1)
  }
  return { rows, cols }
}

export function rangeValues(
  range: A1Range,
  tabs: readonly SheetTab[] = [range.tab],
  render = 'FORMATTED_VALUE',
): JsonValue[][] {
  const evaluator = new FormulaEvaluator(tabs)
  const extent = tabExtent(range.tab)
  const endRow = Math.min(range.endRow ?? extent.rows - 1, extent.rows - 1)
  const endCol = range.endCol ?? extent.cols - 1
  const out: JsonValue[][] = []
  for (let r = range.startRow; r <= endRow; r += 1) {
    const row: JsonValue[] = []
    for (let c = range.startCol; c <= endCol; c += 1) {
      const key = `${String(r)},${String(c)}`
      const entered = enteredValue(range.tab, key)
      if (render === 'FORMULA' && typeof entered.formulaValue === 'string') {
        row.push(entered.formulaValue)
      } else {
        const data = evaluatedCell(range.tab, r, c, evaluator)
        const value = asObj(data.effectiveValue)
        row.push(
          render === 'UNFORMATTED_VALUE' || render === 'FORMULA'
            ? (value.numberValue ??
                value.boolValue ??
                value.stringValue ??
                data.formattedValue ??
                '')
            : (data.formattedValue ?? ''),
        )
      }
    }
    while (row.length > 0 && row[row.length - 1] === '') row.pop()
    out.push(row)
  }
  while (out.length > 0 && (out[out.length - 1] as JsonValue[]).length === 0) out.pop()
  return out
}

export function tabToCsv(tab: SheetTab, tabs: readonly SheetTab[] = [tab]): string {
  const rows = rangeValues(wholeTab(tab), tabs)
  return rows.map((r) => r.join(',')).join('\n') + (rows.length > 0 ? '\n' : '')
}

export function writeValues(
  range: A1Range,
  values: JsonValue[][],
  startRow: number,
  option = 'USER_ENTERED',
): number {
  let cells = 0
  for (let i = 0; i < values.length; i += 1) {
    const row = values[i] as JsonValue[]
    for (let j = 0; j < row.length; j += 1) {
      const value = row[j]
      if (value === null || value === undefined) continue
      if (typeof value !== 'string' && typeof value !== 'number' && typeof value !== 'boolean')
        continue
      const key = `${String(startRow + i)},${String(range.startCol + j)}`
      range.tab.cells.set(key, String(value))
      const props = { ...range.tab.props.get(key) }
      if (value === '') delete props.userEnteredValue
      else props.userEnteredValue = inputValue(value, option)
      range.tab.props.set(key, props)
      cells += 1
    }
  }
  return cells
}

// values.clear and values.batchClear drop the cells inside the rect but
// leave the grid alone, which is what separates them from deleteDimension.
export function clearRange(range: A1Range): void {
  const extent = tabExtent(range.tab)
  const endRow = Math.min(range.endRow ?? extent.rows - 1, extent.rows - 1)
  const endCol = Math.min(range.endCol ?? extent.cols - 1, extent.cols - 1)
  for (let r = range.startRow; r <= endRow; r += 1) {
    for (let c = range.startCol; c <= endCol; c += 1) {
      const key = `${String(r)},${String(c)}`
      range.tab.cells.delete(key)
      const props = range.tab.props.get(key)
      if (props !== undefined) delete props.userEnteredValue
    }
  }
}

// The grid a tab reports, which the live API grows to hold what was
// written: 1313 written rows report rowCount 1313, and rowMetadata has one
// entry per row of the grid rather than a fixed 1000.
export interface Grid {
  rows: number
  cols: number
}

export function tabGrid(tab: SheetTab): Grid {
  const used = tabExtent(tab)
  return { rows: Math.max(tab.rows, used.rows), cols: Math.max(tab.cols, used.cols) }
}

export function evaluatedCell(
  tab: SheetTab,
  row: number,
  col: number,
  evaluator: FormulaEvaluator,
): JsonObj {
  const key = `${String(row)},${String(col)}`
  if (!tab.cells.has(key) || tab.cells.get(key) === '') return {}
  const entered = enteredValue(tab, key)
  const effective = evaluator.cell(tab, row, col)
  const numberFormat = asObj(asObj(tab.props.get(key)?.userEnteredFormat).numberFormat)
  return {
    userEnteredValue: entered,
    effectiveValue: effective,
    formattedValue: formattedValue(
      effective,
      numberFormat,
      typeof entered.numberValue === 'number' && /[eE]/.test(tab.cells.get(key) ?? ''),
    ),
  }
}

// One CellData's value, back into the text a cell stores; null when it
// carries none.
export function cellText(cell: JsonObj): string | null {
  const value = cell.userEnteredValue
  if (value === undefined) return null
  const v = asObj(value)
  if (typeof v.stringValue === 'string') return v.stringValue
  if (typeof v.numberValue === 'number') return String(v.numberValue)
  if (typeof v.boolValue === 'boolean') return v.boolValue ? 'TRUE' : 'FALSE'
  if (typeof v.formulaValue === 'string') return v.formulaValue
  return null
}

export function wholeTab(tab: SheetTab): A1Range {
  return { tab, startRow: 0, startCol: 0, endRow: null, endCol: null }
}

export function tabProperties(tab: SheetTab, index: number): JsonObj {
  const grid = tabGrid(tab)
  return {
    sheetId: tab.sheetId,
    title: tab.title,
    index,
    sheetType: 'GRID',
    gridProperties: { rowCount: grid.rows, columnCount: grid.cols },
  }
}
