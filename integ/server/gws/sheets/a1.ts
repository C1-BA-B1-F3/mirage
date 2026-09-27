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
import type { SheetTab, Spreadsheet } from '../store/types.ts'

export function colLetterToIndex(letters: string): number {
  let n = 0
  for (const c of letters) n = n * 26 + (c.charCodeAt(0) - 64)
  return n - 1
}

export function colIndexToLetter(col: number): string {
  let n = col + 1
  let out = ''
  while (n > 0) {
    const rem = (n - 1) % 26
    out = String.fromCharCode(65 + rem) + out
    n = Math.floor((n - 1) / 26)
  }
  return out
}

export interface A1Range {
  tab: SheetTab
  startRow: number
  startCol: number
  endRow: number | null
  endCol: number | null
}

export function parseCell(ref: string): { row: number | null; col: number | null } {
  const m = /^([A-Z]*)(\d*)$/.exec(ref.toUpperCase())
  if (m === null) return { row: null, col: null }
  const col = (m[1] as string) !== '' ? colLetterToIndex(m[1] as string) : null
  const row = (m[2] as string) !== '' ? parseInt(m[2] as string, 10) - 1 : null
  return { row, col }
}

// What an unquoted range with no `!` has to look like before it is read as
// cells rather than as a tab name. Every A1 form the real API takes with a
// half open side is here: `A1`, `A1:G9`, a whole column span `A:Z`, and a
// whole row span `1:5`. gspread asks for `A:Z` to mean "every row of the
// first sheet", which `^[A-Z]+\d` used to reject for want of a digit.
const A1_ONLY = /^([A-Z]+\d*|\d+)(:([A-Z]+\d*|\d+))?$/i

// A quoted tab name is quoted whether or not a !cells part follows it, and
// an apostrophe inside it is doubled: gspread sends 'Jun-Jul_2025' for a
// whole worksheet, which lastIndexOf('!') alone cannot see.
export function splitRange(range: string): { tabName: string; cells: string } | null {
  if (range.startsWith("'")) {
    let at = 1
    let name = ''
    while (at < range.length && range[at] !== "'") {
      name += range[at]
      at += 1
    }
    while (range[at] === "'" && range[at + 1] === "'") {
      name += "'"
      at += 2
      while (at < range.length && range[at] !== "'") {
        name += range[at]
        at += 1
      }
    }
    if (at >= range.length) return null
    const rest = range.slice(at + 1)
    if (rest === '') return { tabName: name, cells: '' }
    if (!rest.startsWith('!')) return null
    return { tabName: name, cells: rest.slice(1) }
  }
  const bang = range.lastIndexOf('!')
  if (bang === -1) return null
  return { tabName: range.slice(0, bang), cells: range.slice(bang + 1) }
}

export function parseA1(sheet: Spreadsheet, range: string): A1Range | null {
  let tabName = ''
  let cells = range
  const split = splitRange(range)
  if (split !== null) {
    tabName = split.tabName
    cells = split.cells
  } else if (
    // A bare range names a sheet tab first ("Sheet1" is a tab, not the
    // cell SHEET1), matching the real API's resolution order.
    sheet.tabs.some((t) => t.title === range) ||
    !A1_ONLY.test(range)
  ) {
    tabName = range
    cells = ''
  }
  const tab = tabName === '' ? sheet.tabs[0] : sheet.tabs.find((t) => t.title === tabName)
  if (tab === undefined) return null
  if (cells === '') return { tab, startRow: 0, startCol: 0, endRow: null, endCol: null }
  const [startRef, endRef] = cells.split(':') as [string, string | undefined]
  const start = parseCell(startRef)
  const end = endRef !== undefined ? parseCell(endRef) : start
  return {
    tab,
    startRow: start.row ?? 0,
    startCol: start.col ?? 0,
    endRow: end.row,
    endCol: end.col,
  }
}

export function rangeLabel(
  tab: SheetTab,
  startRow: number,
  startCol: number,
  values: JsonValue[][],
): string {
  const rows = Math.max(1, values.length)
  const cols = Math.max(1, ...values.map((r) => r.length))
  const start = `${colIndexToLetter(startCol)}${String(startRow + 1)}`
  const end = `${colIndexToLetter(startCol + cols - 1)}${String(startRow + rows)}`
  return `${tab.title}!${start}:${end}`
}

export function rangeLabelFor(range: A1Range, requested: string): string {
  if (requested.includes('!')) return requested
  return `${range.tab.title}!A1:Z1000`
}
