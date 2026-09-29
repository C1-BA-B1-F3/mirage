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

import { SeedError } from './errors.ts'
import { TENANT_FIELD } from './tenant.ts'
import type { JsonValue, TenantKind } from './types.ts'

export const SEQ_FIELD = 'seq'

export interface DmmfField {
  name: string
  dbName?: string | null
  kind: string
  isList: boolean
  isRequired?: boolean
  type: string
  relationName?: string | null
  relationFromFields?: readonly string[] | null
}

export interface DmmfModel {
  name: string
  dbName?: string | null
  fields: readonly DmmfField[]
}

export interface Dmmf {
  datamodel: { models: readonly DmmfModel[] }
}

interface CreateDelegate {
  create(args: { data: Record<string, unknown> }): Promise<unknown>
}

export interface SeedOptions {
  dmmf: Dmmf
  tenant: string
  tenantKind: TenantKind
  roots?: Record<string, string>
}

type Row = Record<string, JsonValue>

export function delegateName(model: string): string {
  return model.charAt(0).toLowerCase() + model.slice(1)
}

// A model the generated client has no delegate for is a schema/client skew:
// the schema declares it and the client predates it, which happens whenever
// `prisma generate` is stale. Reaching through the index without this check
// answered `Cannot read properties of undefined (reading 'create')`, which
// names neither the model nor the real cause.
export function delegateFor<D>(db: unknown, model: string): D {
  const found = (db as Record<string, D | undefined>)[delegateName(model)]
  if (found === undefined) throw new SeedError(`client has no delegate for model ${model}`)
  return found
}

function isRow(v: JsonValue): v is Row {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

function modelByName(dmmf: Dmmf, name: string): DmmfModel {
  const found = dmmf.datamodel.models.find((m) => m.name === name)
  if (found === undefined) throw new SeedError(`no model ${name} in schema`)
  return found
}

// A fixture's top-level key names a model, and the two spellings differ only
// by case and an English plural, so the mapping is derived rather than
// declared. A fake with a key the derivation cannot reach passes `roots`.
function rootModel(dmmf: Dmmf, key: string, roots: Record<string, string>): DmmfModel {
  const override = roots[key]
  if (override !== undefined) return modelByName(dmmf, override)
  const wants = [key, key.replace(/ies$/, 'y'), key.replace(/es$/, ''), key.replace(/s$/, '')].map(
    (s) => s.toLowerCase(),
  )
  const found = dmmf.datamodel.models.find((m) => wants.includes(m.name.toLowerCase()))
  if (found === undefined) throw new SeedError(`fixture key ${key} names no model`)
  return found
}

// Which of the child's own scalars the parent's nested create fills in. Prisma
// refuses a relation scalar in a nested create input, so the seeder must not
// inject `tenant` on a child whose relation already carries it, and must inject
// it on one whose relation does not.
function suppliedByParent(dmmf: Dmmf, parent: DmmfModel, field: DmmfField): readonly string[] {
  const own = field.relationFromFields ?? []
  if (own.length > 0) return []
  const child = modelByName(dmmf, field.type)
  const back = child.fields.find(
    (f) => f.kind === 'object' && f.type === parent.name && f.relationName === field.relationName,
  )
  return back?.relationFromFields ?? []
}

function build(
  dmmf: Dmmf,
  model: DmmfModel,
  row: Row,
  seq: number,
  injectTenant: boolean,
  opts: SeedOptions,
  counts: Record<string, number>,
): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  const has = (name: string): boolean => model.fields.some((f) => f.name === name)
  if (injectTenant && opts.tenantKind !== 'none' && has(TENANT_FIELD) && !(TENANT_FIELD in row)) {
    out[TENANT_FIELD] = opts.tenant
  }
  // Ordering is not free: `include` does not read back insertion order, so
  // every listable table carries seq and the seeder stamps it in fixture
  // order. A fixture that states its own seq keeps it.
  if (has(SEQ_FIELD) && !(SEQ_FIELD in row)) out[SEQ_FIELD] = seq
  for (const [key, value] of Object.entries(row)) {
    const field = model.fields.find((f) => f.name === key)
    if (field === undefined) throw new SeedError(`${model.name} has no field ${key}`)
    if (field.kind !== 'object') {
      out[key] = isRow(value) || Array.isArray(value) ? JSON.stringify(value) : value
      continue
    }
    const childModel = modelByName(dmmf, field.type)
    const supplied = suppliedByParent(dmmf, model, field)
    const inject = !supplied.includes(TENANT_FIELD)
    if (field.isList) {
      if (!Array.isArray(value)) throw new SeedError(`${model.name}.${key} wants a list`)
      out[key] = {
        create: value.map((child, i) => {
          if (!isRow(child))
            throw new SeedError(`${model.name}.${key}[${String(i)}] is not an object`)
          return build(dmmf, childModel, child, i, inject, opts, counts)
        }),
      }
      continue
    }
    if (!isRow(value)) throw new SeedError(`${model.name}.${key} wants an object`)
    out[key] = { create: build(dmmf, childModel, value, 0, inject, opts, counts) }
  }
  counts[model.name] = (counts[model.name] ?? 0) + 1
  return out
}

// The whole seeder: no per-entity code anywhere. A fixture is a tree of rows,
// each key is either a scalar column or a relation field named by the schema,
// and Prisma's nested create writes the tree in one call per root row.
export async function seedFixture(
  db: unknown,
  fixture: JsonValue,
  opts: SeedOptions,
): Promise<Record<string, number>> {
  if (!isRow(fixture)) throw new SeedError('fixture root must be an object')
  const roots = opts.roots ?? {}
  const counts: Record<string, number> = {}
  const delegates = db as Record<string, CreateDelegate>
  for (const [key, value] of Object.entries(fixture)) {
    const model = rootModel(opts.dmmf, key, roots)
    const rows = Array.isArray(value) ? value : [value]
    let seq = 0
    for (const row of rows) {
      if (!isRow(row)) throw new SeedError(`fixture ${key}[${String(seq)}] is not an object`)
      const data = build(opts.dmmf, model, row, seq, true, opts, counts)
      await delegateFor<CreateDelegate>(delegates, model.name).create({ data })
      seq += 1
    }
  }
  // Sorted so the /reset response is byte-stable: the raw insertion order is
  // nested-create completion order, which reads as a diff when it is not one.
  return Object.fromEntries(Object.entries(counts).sort(([a], [b]) => (a < b ? -1 : 1)))
}
