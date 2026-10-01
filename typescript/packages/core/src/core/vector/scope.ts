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

import { contentTypeForExtension } from '../../utils/filetype.ts'
import { Codec } from '../hierarchy/codec.ts'
import { Scope, Slot, type ScopeMatch } from '../hierarchy/scope.ts'
import type { Leaf } from './types.ts'

/** The leaf a blob column renders as, one file per row. */
export function blobLeaf(ext: string): Leaf {
  return ['row_blob', new Codec({ suffix: `.${ext}` }), contentTypeForExtension(ext)]
}

/**
 * A mount's scope table, shaped by its config.
 *
 * The tree is a function of the mount config, not of the backend: a pinned
 * table removes the leading table segment, every `groupBy` column adds one
 * directory level, and each leaf adds one file per row. Group slots are named
 * positionally (`g0`, `g1`, ...) so a column named `table` cannot collide with
 * the table slot; `filtersOf` maps them back to column names. Every partial
 * depth shares the one `group` kind, and its lister derives the depth from the
 * slots, so the lister table stays static while the scope table varies per
 * mount.
 */
export function rowScopes(
  pinned: boolean,
  groups: readonly Codec[],
  leaves: readonly Leaf[],
): Scope[] {
  const prefix: Slot[] = pinned ? [] : [new Slot('table')]
  const slots = groups.map((codec, i) => new Slot(`g${String(i)}`, codec))
  const scopes: Scope[] = []
  for (let depth = 0; depth <= slots.length; depth++) {
    if (depth === 0 && prefix.length === 0) continue
    scopes.push(new Scope({ kind: 'group', segments: [...prefix, ...slots.slice(0, depth)] }))
  }
  for (const [kind, codec, filetype] of leaves) {
    scopes.push(
      new Scope({
        kind,
        segments: [...prefix, ...slots, new Slot('row_id', codec)],
        leaf: true,
        filetype,
      }),
    )
  }
  return scopes
}

/** The table a match addresses: pinned, or the path's first slot. */
export function tableOf(pinned: string | null, match: ScopeMatch): string {
  return pinned ?? match.slots.table ?? ''
}

/** The match's group filters, keyed back to column names. */
export function filtersOf(groupBy: readonly string[], match: ScopeMatch): Record<string, string> {
  const filters: Record<string, string> = {}
  for (const [i, column] of groupBy.entries()) {
    const value = match.slots[`g${String(i)}`]
    if (value === undefined) break
    filters[column] = value
  }
  return filters
}
