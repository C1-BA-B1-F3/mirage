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

export type JsonObj = { [key: string]: JsonValue }

export function isObj(v: JsonValue | undefined): v is JsonObj {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

export function asObj(v: JsonValue | undefined): JsonObj {
  return isObj(v) ? v : {}
}

export function asArr(v: JsonValue | undefined): JsonValue[] {
  return Array.isArray(v) ? v : []
}

export function asObjArr(v: JsonValue | undefined): JsonObj[] {
  return asArr(v).filter(isObj)
}

export function asStr(v: JsonValue | undefined): string | undefined {
  return typeof v === 'string' ? v : undefined
}

export function asNum(v: JsonValue | undefined): number | undefined {
  return typeof v === 'number' ? v : undefined
}

export function asBool(v: JsonValue | undefined): boolean | undefined {
  return typeof v === 'boolean' ? v : undefined
}

export function asStrArr(v: JsonValue | undefined): string[] | undefined {
  if (!Array.isArray(v)) return undefined
  return v.every((e) => typeof e === 'string') ? (v as string[]) : undefined
}

// Keep wire types so RAW strings remain distinguishable from numbers.
export function asGrid(v: JsonValue | undefined): JsonValue[][] {
  return asArr(v).map(asArr)
}
