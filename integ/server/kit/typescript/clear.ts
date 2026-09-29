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
import type { Dmmf } from './seed.ts'
import { TENANT_FIELD } from './tenant.ts'

interface DeleteClient {
  $executeRawUnsafe(query: string, ...values: string[]): Promise<number>
}

function identifier(name: string): string {
  return `"${name.replaceAll('"', '""')}"`
}

// The precondition a scoped reset cannot check at compile time. Recreating the
// run file "cannot leave a table the fake forgot to clear"; deleting by tenant
// can, and in exactly one way: a model with no tenant column holds rows every
// tenant shares, so clearing one tenant would leave them behind and its next
// seed would read the previous run's state as its own. That is a cross-host
// flake, which is the worst kind to debug, so it is refused at reset time.
export function untenanted(dmmf: Dmmf): string[] {
  return dmmf.datamodel.models
    .filter((m) => !m.fields.some((f) => f.name === TENANT_FIELD))
    .map((m) => m.name)
    .sort()
}

// `relationMode = "prisma"` does not mean order is free, it means the opposite:
// it moves referential integrity OUT of SQLite and INTO the client, so Prisma
// itself refuses to delete a row another row still requires. Deleting in
// declaration order answered `The change you are trying to make would violate
// the required relation 'BoardToOwner'`, and the reset 500'd.
//
// So the FK holders go first. An edge is a relation field that is REQUIRED and
// carries `relationFromFields`: required because that is exactly the set Prisma
// blocks on (an optional one it nulls instead), and carrying the fields because
// the other end of the same relation is a back-reference that holds no key. A
// cycle among required edges is a schema no row could satisfy in the first
// place, so it is named rather than worked around.
export function deleteOrder(dmmf: Dmmf): string[] {
  const models = dmmf.datamodel.models.map((m) => m.name)
  const needs = new Map<string, Set<string>>(
    dmmf.datamodel.models.map((m) => [
      m.name,
      new Set(
        m.fields
          .filter(
            (f) =>
              f.kind === 'object' &&
              f.isRequired === true &&
              (f.relationFromFields ?? []).length > 0 &&
              f.type !== m.name,
          )
          .map((f) => f.type),
      ),
    ]),
  )
  // Built pointed-at first (Board before Card), which is the order rows have to
  // be CREATED in, and then reversed. Deleting is the same dependency read
  // backwards, and doing the sort in the natural direction keeps that one
  // reversal as the only place the two orders differ.
  const placed: string[] = []
  const done = new Set<string>()
  while (placed.length < models.length) {
    const ready = models.filter(
      (m) => !done.has(m) && [...(needs.get(m) ?? [])].every((dep) => done.has(dep)),
    )
    if (ready.length === 0) {
      const stuck = models.filter((m) => !done.has(m)).sort()
      throw new SeedError(`required relations form a cycle among ${stuck.join(', ')}`)
    }
    for (const m of ready) {
      placed.push(m)
      done.add(m)
    }
  }
  return placed.reverse()
}

// Driven by the DMMF, not by a per-fake list, for the same reason the seeder
// is: a model added to a schema is cleared without anyone remembering to say so.
export async function clearTenants(db: unknown, dmmf: Dmmf, tenants: string[]): Promise<number> {
  const missing = untenanted(dmmf)
  if (missing.length > 0) {
    throw new SeedError(
      `a scoped reset needs a ${TENANT_FIELD} column on every model; missing on ${missing.join(', ')}`,
    )
  }
  // Prisma's relation emulation materializes every matching key even for
  // deleteMany. Reset owns the entire tenant, so delete directly in SQLite;
  // memory is bounded by the statement size, not the tenant's row count.
  const client = db as DeleteClient
  let removed = 0
  for (const name of deleteOrder(dmmf)) {
    const model = dmmf.datamodel.models.find((m) => m.name === name)!
    const field = model.fields.find((f) => f.name === TENANT_FIELD)!
    for (const tenant of tenants) {
      removed += await client.$executeRawUnsafe(
        `DELETE FROM ${identifier(model.dbName ?? model.name)} WHERE ${identifier(field.dbName ?? field.name)} = ?`,
        tenant,
      )
    }
  }
  return removed
}
