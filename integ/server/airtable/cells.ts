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

import type { JsonValue } from '../kit/typescript/index.ts'
import { MAX_DEPTH } from './config.ts'
import { FormulaSyntaxError, UnknownFieldsError, compile, evaluate, toText } from './formula.ts'
import type { FValue } from './formula.ts'
import { fieldById, fieldByRef, optString, recordIn, tableById } from './store.ts'
import type { FieldRow, RecordRow, TableRow, World } from './store.ts'
import { badChoice, badValue, computedField, isId, isObject, refuse } from './wire.ts'
import type { JsonObject } from './wire.ts'

// The read-only field types. A write naming one is refused whatever the value.
export const COMPUTED = new Set([
  'formula',
  'rollup',
  'lookup',
  'multipleLookupValues',
  'count',
  'autoNumber',
  'createdTime',
  'lastModifiedTime',
  'createdBy',
  'lastModifiedBy',
  'button',
  'aiText',
  'externalSyncSource',
])

// Of those, the ones this fake DERIVES on every read, so a write elsewhere
// keeps them true: a record's own timestamps and number, a link's count and
// lookups through it, and a formula in the subset formula.ts evaluates. The
// rest (rollup, createdBy, button, ...) render whatever the fixture stored.
export const DERIVED = new Set([
  'formula',
  'multipleLookupValues',
  'count',
  'autoNumber',
  'createdTime',
  'lastModifiedTime',
])

// What the API leaves out of `fields` rather than rendering: "", [], false
// and null. 0 is a value.
export function isEmpty(v: JsonValue | undefined): boolean {
  return (
    v === undefined || v === null || v === '' || v === false || (Array.isArray(v) && v.length === 0)
  )
}

function collaborator(world: World, ref: JsonValue | undefined): JsonValue | undefined {
  if (!isObject(ref) || typeof ref.id !== 'string') return undefined
  const user = world.users.get(ref.id)
  return user === undefined ? undefined : { id: user.id, email: user.email, name: user.name }
}

function lookupValues(
  world: World,
  table: TableRow,
  rec: RecordRow,
  field: FieldRow,
  depth: number,
): JsonValue[] {
  const link = fieldById(table, optString(field, 'recordLinkFieldId') ?? '')
  if (link === undefined) return []
  const linked = tableById(world, optString(link, 'linkedTableId') ?? '')
  const target =
    linked === undefined
      ? undefined
      : fieldById(linked, optString(field, 'fieldIdInLinkedTable') ?? '')
  const ids = rec.cells[link.id]
  if (linked === undefined || target === undefined || !Array.isArray(ids)) return []
  const out: JsonValue[] = []
  for (const id of ids) {
    const other = typeof id === 'string' ? recordIn(linked, id) : undefined
    if (other === undefined) continue
    const v = cellValue(world, linked, other, target, depth + 1)
    if (Array.isArray(v)) out.push(...v.filter((x) => !isEmpty(x)))
    else if (v !== undefined && !isEmpty(v)) out.push(v)
  }
  return out
}

function objectText(v: JsonObject): string {
  for (const key of ['name', 'filename', 'text', 'label']) {
    const s = v[key]
    if (typeof s === 'string') return s
  }
  return ''
}

// The primary field's text, which is what a linked record reads as inside a
// formula (and what Airtable's UI shows in a link cell).
function primaryText(world: World, tableId: string, id: string, depth: number): string {
  const table = tableById(world, tableId)
  const rec = table === undefined ? undefined : recordIn(table, id)
  const primary = table === undefined ? undefined : fieldById(table, table.primaryFieldId)
  if (table === undefined || rec === undefined || primary === undefined) return id
  return toText(scalar(world, primary, cellValue(world, table, rec, primary, depth + 1), depth + 1))
}

// A cell as a formula sees it: arrays join with ", " (a link by its records'
// primary values), a collaborator is its name, an attachment its filename.
export function scalar(
  world: World,
  field: FieldRow,
  v: JsonValue | undefined,
  depth: number,
): FValue {
  if (v === undefined || v === null) return null
  // A date reads as its midnight-UTC instant, compared and joined alike:
  // `{Due} = "2021-02-02T00:00:00.000Z"` and `{Due} & ""` match a 2021-02-02
  // cell as that text, and `{Due} = "2021-02-02"` does not (MCP-Atlas's
  // recorded search_records, replayed by integ/airtable_atlas.ts, and live
  // Airtable on 2026-09-25).
  if (field.type === 'date' && typeof v === 'string') return `${v}T00:00:00.000Z`
  if (typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean') return v
  if (!Array.isArray(v)) return objectText(v)
  const linkedTable =
    field.type === 'multipleRecordLinks' ? optString(field, 'linkedTableId') : undefined
  const parts = v
    .map((item) => {
      if (linkedTable !== undefined && typeof item === 'string') {
        return primaryText(world, linkedTable, item, depth)
      }
      if (isObject(item)) return objectText(item)
      return typeof item === 'string' || typeof item === 'number' || typeof item === 'boolean'
        ? toText(item)
        : ''
    })
    .filter((s) => s !== '')
  return parts.length === 0 ? null : parts.join(', ')
}

// A formula is compiled against the table it lives in, where a reference may
// name a field by id (the vendor's own spelling in options.formula) or name.
export function compileIn(table: TableRow, src: string): ReturnType<typeof compile> {
  return compile(src, (ref) => fieldByRef(table, ref)?.id)
}

// A field as a formula reads it. A formula field in error ({error} or
// {specialValue}, the only objects formulaValue renders) stays an error, so
// ISERROR() catches it and operators carry it on, as Airtable does for a
// referenced #ERROR! (https://support.airtable.com/docs/catching-errors-with-logical-functions).
export function formulaInput(
  world: World,
  table: TableRow,
  rec: RecordRow,
  fieldId: string,
  depth: number,
): FValue {
  const field = fieldById(table, fieldId)
  if (field === undefined) return null
  const v = cellValue(world, table, rec, field, depth)
  if (field.type === 'formula' && isObject(v)) return Number.NaN
  return scalar(world, field, v, depth)
}

function formulaValue(
  world: World,
  table: TableRow,
  rec: RecordRow,
  field: FieldRow,
  depth: number,
): JsonValue | undefined {
  const src = optString(field, 'formula')
  if (src === undefined) return undefined
  let v: FValue
  try {
    const compiled = compileIn(table, src)
    v = evaluate(compiled, {
      recordId: rec.id,
      value: (id) => formulaInput(world, table, rec, id, depth + 1),
    })
  } catch (err: unknown) {
    if (err instanceof FormulaSyntaxError || err instanceof UnknownFieldsError) {
      return { error: '#ERROR!' }
    }
    throw err
  }
  if (typeof v === 'number' && !Number.isFinite(v)) return { specialValue: 'NaN' }
  return v === null ? undefined : v
}

// One cell as the API renders it (json cellFormat). Derived fields are
// computed here from the record and its links; everything else is the stored
// value, with a collaborator expanded from its id to the full user.
export function cellValue(
  world: World,
  table: TableRow,
  rec: RecordRow,
  field: FieldRow,
  depth = 0,
): JsonValue | undefined {
  if (depth > MAX_DEPTH) return undefined
  switch (field.type) {
    case 'createdTime':
      return rec.createdTime
    case 'lastModifiedTime':
      return rec.modifiedTime
    case 'autoNumber':
      return rec.autoNumber
    case 'count': {
      const ids = rec.cells[optString(field, 'recordLinkFieldId') ?? '']
      return Array.isArray(ids) ? ids.length : 0
    }
    case 'multipleLookupValues':
      return lookupValues(world, table, rec, field, depth)
    case 'formula':
      return formulaValue(world, table, rec, field, depth)
    case 'singleCollaborator':
      return collaborator(world, rec.cells[field.id])
    case 'multipleCollaborators': {
      const refs = rec.cells[field.id]
      if (!Array.isArray(refs)) return undefined
      const out: JsonValue[] = []
      for (const ref of refs) {
        const user = collaborator(world, ref)
        if (user !== undefined) out.push(user)
      }
      return out
    }
    default:
      return rec.cells[field.id]
  }
}

export function renderRecord(
  world: World,
  table: TableRow,
  rec: RecordRow,
  byId: boolean,
  only: ReadonlySet<string> | null = null,
): JsonObject {
  const fields: JsonObject = {}
  for (const field of table.fields) {
    if (only !== null && !only.has(field.id)) continue
    const v = cellValue(world, table, rec, field)
    if (v === undefined || isEmpty(v)) continue
    fields[byId ? field.id : field.name] = v
  }
  return { id: rec.id, createdTime: rec.createdTime, fields }
}

// The write side. `mint` hands out ids for what a write creates (a typecast
// select option, an attachment added by URL); `seeding` is afterSeed reusing
// this validation on fixture cells, where attachments arrive already whole.
export interface WriteCtx {
  world: World
  typecast: boolean
  mint: (kind: 'sel' | 'att') => string
  seeding: boolean
}

function choose(w: WriteCtx, field: FieldRow, name: string): string {
  const choices = field.options?.choices
  const list = Array.isArray(choices) ? choices : []
  for (const c of list) if (isObject(c) && c.name === name) return name
  if (!w.typecast) return refuse(badChoice(name))
  const options: JsonObject = field.options ?? {}
  options.choices = [...list, { id: w.mint('sel'), name }]
  field.options = options
  field.dirty = true
  return name
}

function userRef(w: WriteCtx, field: FieldRow, value: JsonValue): JsonValue {
  if (isObject(value)) {
    if (typeof value.id === 'string' && w.world.users.has(value.id)) return { id: value.id }
    if (typeof value.email === 'string') {
      for (const u of w.world.users.values()) if (u.email === value.email) return { id: u.id }
    }
  }
  return refuse(badValue(field.name))
}

function recordLinks(w: WriteCtx, field: FieldRow, value: JsonValue): JsonValue | undefined {
  const raw = w.typecast && typeof value === 'string' ? [value] : value
  if (!Array.isArray(raw)) return refuse(badValue(field.name))
  const linked = tableById(w.world, optString(field, 'linkedTableId') ?? '')
  const out: string[] = []
  for (const id of raw) {
    if (typeof id !== 'string' || !isId('rec', id) || linked === undefined) {
      return refuse(badValue(field.name))
    }
    if (recordIn(linked, id) === undefined) return refuse(badValue(field.name))
    if (!out.includes(id)) out.push(id)
  }
  return out.length === 0 ? undefined : out
}

function lastSegment(url: string): string {
  try {
    const parts = new URL(url).pathname.split('/').filter((p) => p !== '')
    return decodeURIComponent(parts[parts.length - 1] ?? 'attachment')
  } catch {
    return 'attachment'
  }
}

// An attachment write lists the attachments the cell should END with: an
// existing one by its id (kept as it is), a new one by url (and optional
// filename). A fixture's attachments are whole objects and kept verbatim.
function attachments(
  w: WriteCtx,
  field: FieldRow,
  value: JsonValue,
  current: JsonValue | undefined,
): JsonValue | undefined {
  if (!Array.isArray(value)) return refuse(badValue(field.name))
  const existing = Array.isArray(current) ? current.filter(isObject) : []
  const out: JsonValue[] = []
  for (const item of value) {
    if (!isObject(item)) return refuse(badValue(field.name))
    if (w.seeding) {
      const whole =
        typeof item.id === 'string' &&
        isId('att', item.id) &&
        typeof item.url === 'string' &&
        typeof item.filename === 'string'
      if (!whole) return refuse(badValue(field.name))
      out.push(item)
      continue
    }
    if (typeof item.id === 'string') {
      const kept = existing.find((a) => a.id === item.id)
      if (kept === undefined) return refuse(badValue(field.name))
      out.push(kept)
      continue
    }
    if (typeof item.url !== 'string' || !/^https?:\/\//.test(item.url)) {
      return refuse(badValue(field.name))
    }
    const filename = typeof item.filename === 'string' ? item.filename : lastSegment(item.url)
    out.push({ id: w.mint('att'), url: item.url, filename })
  }
  return out.length === 0 ? undefined : out
}

function text(w: WriteCtx, field: FieldRow, value: JsonValue): JsonValue | undefined {
  if (typeof value === 'string') return value === '' ? undefined : value
  if (w.typecast && (typeof value === 'number' || typeof value === 'boolean')) return String(value)
  return refuse(badValue(field.name))
}

function num(w: WriteCtx, field: FieldRow, value: JsonValue): JsonValue | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (w.typecast && typeof value === 'string') {
    if (value.trim() === '') return undefined
    const n = Number(value)
    if (Number.isFinite(n)) return n
  }
  return refuse(badValue(field.name))
}

function checkbox(w: WriteCtx, field: FieldRow, value: JsonValue): JsonValue | undefined {
  if (typeof value === 'boolean') return value ? true : undefined
  if (w.typecast && typeof value === 'string') {
    const s = value.trim().toLowerCase()
    if (['true', '1', 'yes', 'checked'].includes(s)) return true
    if (['false', '0', 'no', 'unchecked', ''].includes(s)) return undefined
  }
  return refuse(badValue(field.name))
}

function date(field: FieldRow, value: JsonValue): JsonValue | undefined {
  if (typeof value !== 'string') return refuse(badValue(field.name))
  if (value === '') return undefined
  const m = /^(\d{4}-\d{2}-\d{2})(T.*)?$/.exec(value)
  const day = m?.[1]
  if (day === undefined || Number.isNaN(Date.parse(day))) return refuse(badValue(field.name))
  return day
}

function dateTime(field: FieldRow, value: JsonValue): JsonValue | undefined {
  if (typeof value !== 'string') return refuse(badValue(field.name))
  if (value === '') return undefined
  const t = Date.parse(value)
  if (Number.isNaN(t)) return refuse(badValue(field.name))
  return new Date(t).toISOString()
}

// A cell as a write STORES it, or undefined to clear it. Null clears any
// writable field, and so does the empty value of its type ("", [], false).
export function coerce(
  w: WriteCtx,
  field: FieldRow,
  value: JsonValue,
  current: JsonValue | undefined,
): JsonValue | undefined {
  if (COMPUTED.has(field.type)) return refuse(computedField(field.name))
  if (value === null) return undefined
  switch (field.type) {
    case 'singleLineText':
    case 'multilineText':
    case 'richText':
    case 'email':
    case 'url':
    case 'phoneNumber':
      return text(w, field, value)
    case 'number':
    case 'percent':
    case 'currency':
    case 'duration':
    case 'rating':
      return num(w, field, value)
    case 'checkbox':
      return checkbox(w, field, value)
    case 'singleSelect': {
      const name =
        typeof value === 'string'
          ? value
          : w.typecast && typeof value === 'number'
            ? String(value)
            : null
      if (name === null) return refuse(badValue(field.name))
      return name === '' ? undefined : choose(w, field, name)
    }
    case 'multipleSelects': {
      const names =
        Array.isArray(value) && value.every((v) => typeof v === 'string')
          ? (value as string[])
          : w.typecast && typeof value === 'string'
            ? value
                .split(',')
                .map((s) => s.trim())
                .filter((s) => s !== '')
            : null
      if (names === null) return refuse(badValue(field.name))
      const out: string[] = []
      for (const name of names) {
        const kept = choose(w, field, name)
        if (!out.includes(kept)) out.push(kept)
      }
      return out.length === 0 ? undefined : out
    }
    case 'date':
      return date(field, value)
    case 'dateTime':
      return dateTime(field, value)
    case 'singleCollaborator':
      return userRef(w, field, value)
    case 'multipleCollaborators': {
      if (!Array.isArray(value)) return refuse(badValue(field.name))
      const out = value.map((v) => userRef(w, field, v))
      return out.length === 0 ? undefined : out
    }
    case 'multipleRecordLinks':
      return recordLinks(w, field, value)
    case 'multipleAttachments':
      return attachments(w, field, value, current)
    case 'barcode':
      if (!isObject(value) || typeof value.text !== 'string') return refuse(badValue(field.name))
      return value
    default:
      return refuse(badValue(field.name))
  }
}
