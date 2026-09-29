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

import { parseConfig, schemaFor } from '../kit/typescript/index.ts'
import type { PrismaClient } from '../../generated/airtable/index.js'

export type C = PrismaClient

// A caller isolates itself by RUN, never by token. Airtable tokens are data in
// this world: two of them (full access and one base) have to see the SAME
// bases and each other's writes, so a token cannot also be the tenant the way
// notion's and slack's are. The run rides the base URL as `/_run/<id>`, which
// gives every caller its own SQLite file; the tenant column is still here
// because it is what makes a fresh run a copy of an already-seeded template.
//
// mintSharing is per kind so a created record and a created comment each
// count from 1 (recNew00000000001, comNew00000000001) whatever the other did.
export const config = parseConfig({
  service: 'airtable',
  schema: schemaFor('airtable'),
  defaultPort: 5084,
  tenantKind: 'pk-column',
  mintSharing: 'per-kind',
})

export const MAX_PAGE_SIZE = 100
export const MAX_BATCH = 10
export const BASES_PAGE = 1000
export const DEFAULT_PAGE_CAP = 100
export const JSON_TYPE = 'application/json; charset=utf-8'
// Formulas, lookups and lookups-of-formulas nest; a fixture that made them
// cycle would otherwise recurse until the stack gave out.
export const MAX_DEPTH = 8
