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

import { z } from 'zod'

export const ResourceType = Object.freeze({
  FILE: 'file',
  FOLDER: 'folder',
} as const)

export type ResourceType = (typeof ResourceType)[keyof typeof ResourceType]

export const LookupStatus = Object.freeze({
  EXPIRED: 'expired',
  NOT_FOUND: 'not_found',
} as const)

export type LookupStatus = (typeof LookupStatus)[keyof typeof LookupStatus]

export const IndexType = Object.freeze({
  RAM: 'ram',
  REDIS: 'redis',
} as const)

export type IndexType = (typeof IndexType)[keyof typeof IndexType]

/**
 * The wire form of an entry: what pydantic writes for the Python
 * `IndexEntry`, snake_case and every field, so a row either language writes
 * is one the other reads. Requiredness mirrors the pydantic model, so a row
 * missing `resource_type` is refused rather than decoded with the field
 * empty. `extra` rides along because it is load-bearing (`size_bytes`, the
 * `folder.childCount` that `find -empty` reads on Graph backends).
 */
export const IndexEntryWireSchema = z.object({
  id: z.string(),
  name: z.string(),
  resource_type: z.string(),
  remote_time: z.string().default(''),
  index_time: z.string().default(''),
  vfs_name: z.string().default(''),
  size: z.number().int().nullable().default(null),
  extra: z.record(z.string(), z.unknown()).default({}),
})

export type IndexEntryWire = z.output<typeof IndexEntryWireSchema>

export interface IndexEntryInit {
  id: string
  name: string
  resourceType: string
  remoteTime?: string
  indexTime?: string
  vfsName?: string
  size?: number | null
  extra?: Record<string, unknown>
}

export class IndexEntry {
  id: string
  name: string
  resourceType: string
  remoteTime: string
  indexTime: string
  vfsName: string
  size: number | null
  extra: Record<string, unknown>

  constructor(init: IndexEntryInit) {
    this.id = init.id
    this.name = init.name
    this.resourceType = init.resourceType
    this.remoteTime = init.remoteTime ?? ''
    this.indexTime = init.indexTime ?? ''
    this.vfsName = init.vfsName ?? ''
    this.size = init.size ?? null
    this.extra = init.extra ?? {}
  }

  copyWith(updates: Partial<IndexEntryInit>): IndexEntry {
    return new IndexEntry({
      id: updates.id ?? this.id,
      name: updates.name ?? this.name,
      resourceType: updates.resourceType ?? this.resourceType,
      remoteTime: updates.remoteTime ?? this.remoteTime,
      indexTime: updates.indexTime ?? this.indexTime,
      vfsName: updates.vfsName ?? this.vfsName,
      size: updates.size !== undefined ? updates.size : this.size,
      extra: updates.extra ?? this.extra,
    })
  }

  /** The wire form, so `JSON.stringify(entry)` is what `model_dump_json` writes. */
  toJSON(): IndexEntryWire {
    return {
      id: this.id,
      name: this.name,
      resource_type: this.resourceType,
      remote_time: this.remoteTime,
      index_time: this.indexTime,
      vfs_name: this.vfsName,
      size: this.size,
      extra: this.extra,
    }
  }

  /** The twin of `model_validate_json`: a row the schema refuses throws. */
  static fromJSON(raw: string): IndexEntry {
    const w = IndexEntryWireSchema.parse(JSON.parse(raw))
    return new IndexEntry({
      id: w.id,
      name: w.name,
      resourceType: w.resource_type,
      remoteTime: w.remote_time,
      indexTime: w.index_time,
      vfsName: w.vfs_name,
      size: w.size,
      extra: w.extra,
    })
  }
}

export interface LookupResult {
  entry?: IndexEntry | null
  status?: LookupStatus | null
}

export interface ListResult {
  entries?: string[] | null
  partialEntries?: string[] | null
  status?: LookupStatus | null
}

/** The directory row, the twin of the pydantic `IndexDirectory`. */
export const IndexDirectorySchema = z.object({
  entries: z.array(z.string()),
  expires_at: z.number(),
  generation: z.string(),
  partial: z.boolean().default(false),
})

export type IndexDirectory = z.output<typeof IndexDirectorySchema>

export interface IndexConfig {
  type?: IndexType
  ttl?: number
}

export interface RedisIndexConfig extends IndexConfig {
  url?: string
  keyPrefix?: string
}
