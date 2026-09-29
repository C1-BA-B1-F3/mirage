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

import type { Ctx, Headers, JsonValue, KitHandler, Reply } from '../kit/typescript/index.ts'
import { JSON_TYPE } from './config.ts'

export interface JsonObject {
  [key: string]: JsonValue
}

// Every refusal is thrown as one of these and turned back into its reply by
// `guard`, so validation several calls deep can stop the request without each
// layer threading a Reply | Value union back up.
export class Refusal extends Error {
  readonly reply: Reply

  constructor(reply: Reply) {
    super(`airtable refusal ${String(reply.status)}`)
    this.reply = reply
  }
}

export function refuse(reply: Reply): never {
  throw new Refusal(reply)
}

export function guard<C>(fn: KitHandler<C>): KitHandler<C> {
  return async (ctx: Ctx<C>): Promise<Reply> => {
    try {
      return await fn(ctx)
    } catch (err: unknown) {
      if (err instanceof Refusal) return err.reply
      throw err
    }
  }
}

export function json(status: number, body: JsonValue): Reply {
  return { status, body, headers: { 'Content-Type': JSON_TYPE } }
}

export function ok(body: JsonValue): Reply {
  return json(200, body)
}

export function apiError(status: number, type: string, message: string): Reply {
  return json(status, { error: { type, message } })
}

// The one error Airtable spells as a bare string: a path no route matches, or
// an id in the path that is not shaped like one. Both are decided before the
// token is looked at, so a malformed id answers this even with no token.
export function notFound(): Reply {
  return json(404, { error: 'NOT_FOUND' })
}

export function authRequired(): Reply {
  return apiError(401, 'AUTHENTICATION_REQUIRED', 'Authentication required')
}

// Unknown and ungranted are one answer on purpose, so a token cannot probe
// for bases or tables it was not given.
export function modelNotFound(): Reply {
  return apiError(
    403,
    'INVALID_PERMISSIONS_OR_MODEL_NOT_FOUND',
    'Invalid permissions, or the requested model was not found. Check that both your user and your token have the required permissions, and that the model names and/or ids are correct.',
  )
}

export function notPermitted(): Reply {
  return apiError(403, 'INVALID_PERMISSIONS', 'You are not permitted to perform this operation')
}

export function invalidRequest(): Reply {
  return apiError(
    422,
    'INVALID_REQUEST_UNKNOWN',
    'Invalid request: parameter validation failed. Check your request data.',
  )
}

export function badBody(): Reply {
  return apiError(422, 'INVALID_REQUEST_BODY', 'Could not parse request body')
}

// A batch update or replace naming a record the table does not hold. A
// single-record route answers modelNotFound instead, as live Airtable does.
export function rowDoesNotExist(id: string): Reply {
  return apiError(422, 'ROW_DOES_NOT_EXIST', `Record ID ${id} does not exist in this table`)
}

// A batch delete naming a record the table does not hold: the one NOT_FOUND
// that carries a message.
export function deleteNotFound(id: string): Reply {
  return apiError(404, 'NOT_FOUND', `Could not find a record with ID "${id}".`)
}

// An edit or delete of a comment the record does not hold. The edit names the
// comment; the delete answers the type alone, with no message.
export function rowCommentDoesNotExist(id: string | null): Reply {
  const error: JsonObject = { type: 'ROW_COMMENT_DOES_NOT_EXIST' }
  if (id !== null) error.message = `Row comment with id ${id} does not exist`
  return json(422, { error })
}

export function commentNotFound(): Reply {
  return apiError(404, 'MODEL_ID_NOT_FOUND', 'Comment not found')
}

export function unknownField(name: string): Reply {
  return apiError(422, 'UNKNOWN_FIELD_NAME', `Unknown field name: "${name}"`)
}

export function computedField(name: string): Reply {
  return apiError(
    422,
    'INVALID_VALUE_FOR_COLUMN',
    `Field "${name}" cannot accept a value because the field is computed`,
  )
}

export function badValue(name: string): Reply {
  return apiError(
    422,
    'INVALID_VALUE_FOR_COLUMN',
    `Field "${name}" cannot accept the provided value`,
  )
}

export function badChoice(value: string): Reply {
  return apiError(
    422,
    'INVALID_MULTIPLE_CHOICE_OPTIONS',
    `Insufficient permissions to create new select option "${JSON.stringify(value)}"`,
  )
}

export function badOffset(value: string): Reply {
  return apiError(422, 'INVALID_OFFSET_VALUE', `The value of offset ${value} is invalid`)
}

// A view id that names a view of another table in the same base: live
// Airtable answers the type alone, with no message.
export function failedStateCheck(): Reply {
  return json(422, { error: { type: 'FAILED_STATE_CHECK' } })
}

// A view named by id is looked up as an id, anything else as a name.
export function viewNotFound(value: string): Reply {
  const type = isId('viw', value) ? 'VIEW_ID_NOT_FOUND' : 'VIEW_NAME_NOT_FOUND'
  return apiError(422, type, `View ${value} not found`)
}

export const INVALID_FORMULA = 'Invalid formula. Please check your formula text.'

export function badFormula(detail: string): Reply {
  return apiError(
    422,
    'INVALID_FILTER_BY_FORMULA',
    `The formula for filtering records is invalid: ${detail}`,
  )
}

// PATCH and PUT carry an id per record and POST does not, so the create twin
// drops that clause; DELETE names ids in the query string instead of objects.
export function badRecords(kind: 'create' | 'update' | 'delete'): Reply {
  const message =
    kind === 'update'
      ? 'You must provide an array of up to 10 record objects, each with an "id" ID field and a "fields" object for cell values.'
      : kind === 'create'
        ? 'You must provide an array of up to 10 record objects, each with a "fields" object for cell values.'
        : 'You must provide an array of up to 10 record IDs.'
  return apiError(422, 'INVALID_RECORDS', message)
}

// Every id Airtable mints is a three-letter kind and fourteen base-62
// characters, and a path id that is not shaped like one never reaches a
// lookup.
const ID_BODY_RE = /^[0-9A-Za-z]{14}$/

export function isId(prefix: string, value: string): boolean {
  return value.length === 17 && value.startsWith(prefix) && ID_BODY_RE.test(value.slice(3))
}

export function isObject(value: JsonValue | undefined): value is JsonObject {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function headerOf(headers: Headers, name: string): string | undefined {
  const raw = headers[name]
  const one = Array.isArray(raw) ? raw[0] : raw
  return one === undefined || one === '' ? undefined : one
}

export function bearerOf(headers: Headers): string | undefined {
  const auth = headerOf(headers, 'authorization')
  if (auth === undefined) return undefined
  const m = /^Bearer\s+(\S+)\s*$/i.exec(auth)
  return m === null ? undefined : m[1]
}

// A write body is JSON or a 422, and a body sent without saying it is JSON is
// one Airtable cannot parse either. An EMPTY body is an empty object, so a
// bodiless POST reaches the same validation a `{}` does.
export function bodyOf<C>(ctx: Ctx<C>): JsonObject {
  if (ctx.body.length === 0) return {}
  const type = headerOf(ctx.headers, 'content-type') ?? ''
  if (!/application\/json/i.test(type)) refuse(badBody())
  let parsed: JsonValue
  try {
    parsed = JSON.parse(ctx.body.toString('utf8')) as JsonValue
  } catch {
    refuse(badBody())
  }
  if (!isObject(parsed)) refuse(invalidRequest())
  return parsed
}

// A body key outside the documented set is refused, not ignored: a caller
// misspelling `typecast` would otherwise write without it and never know.
export function onlyKeys(body: JsonObject, allowed: readonly string[], reply: () => Reply): void {
  for (const key of Object.keys(body)) if (!allowed.includes(key)) refuse(reply())
}

// The three spellings a list parameter arrives in: `name=a`, `name[]=a` (what
// Airtable.js and pyairtable send) and `name[0]=a` (qs's indexed form).
export function listParam(query: URLSearchParams, name: string): string[] | undefined {
  const plain: string[] = []
  const indexed: Array<[number, string]> = []
  let seen = false
  const indexRe = new RegExp(`^${name}\\[(\\d+)\\]$`)
  for (const [key, value] of query) {
    if (key === name || key === `${name}[]`) {
      plain.push(value)
      seen = true
      continue
    }
    const m = indexRe.exec(key)
    if (m !== null) {
      indexed.push([Number(m[1]), value])
      seen = true
    }
  }
  if (!seen) return undefined
  indexed.sort((a, b) => a[0] - b[0])
  return [...plain, ...indexed.map(([, v]) => v)]
}

export function isListKey(key: string, name: string): boolean {
  return key === name || key === `${name}[]` || new RegExp(`^${name}\\[\\d+\\]$`).test(key)
}

// A boolean query parameter, which the API reads from `true`/`false` (and the
// 1/0 a form encoder may send). Anything else is a validation failure.
export function boolParam(raw: string | null): boolean | undefined {
  if (raw === null) return undefined
  if (raw === 'true' || raw === '1') return true
  if (raw === 'false' || raw === '0' || raw === '') return false
  return refuse(invalidRequest())
}

export function intParam(raw: string | null, lo: number, hi: number): number | undefined {
  if (raw === null) return undefined
  const n = Number(raw)
  if (raw.trim() === '' || !Number.isInteger(n) || n < lo || n > hi) refuse(invalidRequest())
  return n
}

export function bodyBool(value: JsonValue | undefined): boolean {
  if (value === undefined || value === null) return false
  if (typeof value !== 'boolean') refuse(invalidRequest())
  return value
}

// The offset a page hands back: `itr`, fourteen digits of position, `/`, and
// the id of the first item on the next page. Stateless on purpose, so a run
// needs no iterator table, and resumable across a write: the next page starts
// at that id wherever it now sits, and only if the id is gone does the
// position decide.
export function offsetToken(position: number, nextId: string): string {
  return `itr${String(position).padStart(14, '0')}/${nextId}`
}

export function parseOffset(raw: string, prefix: string): { position: number; id: string } | null {
  const m = /^itr(\d{14})\/([A-Za-z]{3}[0-9A-Za-z]{14})$/.exec(raw)
  if (m === null) return null
  const id = m[2] ?? ''
  if (!isId(prefix, id)) return null
  return { position: Number(m[1]), id }
}

// Where a page resumes, given the list it pages over.
export function resumeAt(
  list: readonly { id: string }[],
  at: { position: number; id: string },
): number {
  const found = list.findIndex((item) => item.id === at.id)
  return found !== -1 ? found : Math.min(at.position, list.length)
}
