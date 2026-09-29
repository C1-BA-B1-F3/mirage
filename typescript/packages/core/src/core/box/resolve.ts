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

import type { BoxAccessor } from '../../accessor/box.ts'
import type { PathSpec } from '../../types.ts'
import { listFolderItems, type BoxItem, type BoxSearchItem } from './api.ts'

export function pathParts(path: PathSpec): string[] {
  return path.vfsPath.split('/').filter((p) => p !== '')
}

/**
 * Walk folder listings to resolve each component of a path.
 *
 * Box has no path-addressing endpoint, so ids are resolved by listing each
 * level from the mount root. Returns the Box item for every component that
 * resolved, in order; a missing component, or one below a non-folder, ends
 * the chain early.
 */
export async function resolveChain(accessor: BoxAccessor, parts: string[]): Promise<BoxItem[]> {
  const tm = accessor.tokenManager
  let curId = accessor.rootFolderId
  const chain: BoxItem[] = []
  for (const name of parts) {
    if (chain.length > 0 && chain[chain.length - 1]?.type !== 'folder') break
    const children = await listFolderItems(tm, curId)
    const match = children.find((c) => c.name === name)
    if (match === undefined) break
    chain.push(match)
    curId = match.id
  }
  return chain
}

/**
 * Resolve a mount-relative path to its Box item.
 *
 * Returns null if any component is missing, or a non-final component is not
 * a folder.
 */
export async function resolveItem(accessor: BoxAccessor, parts: string[]): Promise<BoxItem | null> {
  const chain = await resolveChain(accessor, parts)
  if (parts.length === 0 || chain.length < parts.length) return null
  return chain[chain.length - 1] ?? null
}

export async function resolveParentId(
  accessor: BoxAccessor,
  parts: string[],
): Promise<string | null> {
  if (parts.length <= 1) return accessor.rootFolderId
  const parent = await resolveItem(accessor, parts.slice(0, -1))
  if (parent?.type !== 'folder') return null
  return parent.id
}

/**
 * Mount-relative path of an item, from its `path_collection`.
 *
 * Box lists an item's ancestors from the account root down to its immediate
 * parent, excluding the item itself; everything up to and including the mount
 * root folder is trimmed. Null when the mount root is not among the
 * ancestors, which is every item outside the mount.
 */
export function mountRelativeKey(
  item: Pick<BoxSearchItem, 'name' | 'path_collection'>,
  rootFolderId: string,
): string | null {
  const entries = item.path_collection?.entries ?? []
  const names: string[] = []
  let collecting = false
  for (const anc of entries) {
    if (collecting) names.push(anc.name)
    if (anc.id === rootFolderId) collecting = true
  }
  if (!collecting) return null
  names.push(item.name)
  return names.filter((n) => n !== '').join('/')
}
