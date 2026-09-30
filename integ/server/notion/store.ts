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

import type { C } from './config.ts'
import { blockToMd } from './text.ts'
import type { BlockRow, DatabaseRow, MetaRow } from './types.ts'
import { databaseIdOf } from './wire.ts'

export async function metaOf(db: C, tenant: string): Promise<MetaRow> {
  const row = await db.notionMeta.findUnique({ where: { tenant } })
  if (row === null) throw new Error(`notion fake: no meta row for tenant ${tenant}`)
  return row
}

// The database a data source id belongs to. The fake derives one data source
// per database, so this is `dataSourceIdOf` run backwards over every database.
export async function dataSourceOwner(
  db: C,
  tenant: string,
  dataSourceId: string,
): Promise<DatabaseRow | null> {
  const all = (await db.notionDatabase.findMany({ where: { tenant } })) as DatabaseRow[]
  const owner = databaseIdOf(dataSourceId, all)
  return all.find((row) => row.id === owner) ?? null
}

export async function childrenOf(db: C, tenant: string, parentId: string): Promise<BlockRow[]> {
  return (await db.notionBlock.findMany({
    where: { tenant, parentId, inTrash: false },
    orderBy: { position: 'asc' },
  })) as BlockRow[]
}

export async function markdownOf(
  db: C,
  tenant: string,
  parentId: string,
  indent: number,
  lines: string[],
): Promise<void> {
  for (const row of await childrenOf(db, tenant, parentId)) {
    const line = blockToMd(row, indent)
    if (line !== '') lines.push(line)
    if (row.hasChildren) await markdownOf(db, tenant, row.id, indent + 1, lines)
  }
}

// The inverse, for POST /v1/pages {markdown}: the official CLI's
