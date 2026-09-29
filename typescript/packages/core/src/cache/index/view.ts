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

import { withCacheMutation } from '../file/io.ts'
import type { FileCache } from '../file/mixin.ts'
import { LookupStatus, type IndexEntry, type ListResult, type LookupResult } from './config.ts'
import { IndexCacheStore } from './store.ts'
import { rstripSlash } from '../../utils/slash.ts'

/** A mount-owned index view; delayed backend writes retain their original owner. */
export class IndexView extends IndexCacheStore {
  constructor(
    private readonly store: IndexCacheStore,
    private readonly cache: FileCache,
    private readonly prefix: string,
    private readonly owns: (path: string) => boolean,
  ) {
    super()
  }

  seed(
    entries: ReadonlyMap<string, IndexEntry>,
    children: ReadonlyMap<string, readonly string[]>,
    expiresAt: Date,
  ): void {
    if (!this.owns(this.prefix)) return
    this.store.seed(
      new Map([...entries].filter(([path]) => this.owns(path))),
      new Map(
        [...children]
          .filter(([path]) => this.owns(path))
          .map(([path, keys]) => [path, keys.filter((key) => this.owns(key))]),
      ),
      expiresAt,
    )
  }

  entries(): Promise<Map<string, IndexEntry>> {
    return withCacheMutation(this.cache, async () => {
      if (!this.owns(this.prefix)) return new Map<string, IndexEntry>()
      const entries = await this.store.entries()
      return new Map([...entries].filter(([path]) => this.owns(path)))
    })
  }

  async get(path: string): Promise<LookupResult> {
    // Index lookups may flush queued state; keep them inside the write fence too.
    return withCacheMutation(this.cache, async () => {
      if (!this.owns(path)) return { status: LookupStatus.NOT_FOUND }
      const result = await this.store.get(path)
      return this.owns(path) ? result : { status: LookupStatus.NOT_FOUND }
    })
  }

  async listDir(path: string): Promise<ListResult> {
    return withCacheMutation(this.cache, async () => {
      if (!this.owns(path)) return { status: LookupStatus.NOT_FOUND }
      const result = await this.store.listDir(path)
      if (!this.owns(path)) return { status: LookupStatus.NOT_FOUND }
      return {
        ...result,
        ...(result.entries == null
          ? {}
          : { entries: result.entries.filter((key) => this.owns(key)) }),
        ...(result.partialEntries == null
          ? {}
          : { partialEntries: result.partialEntries.filter((key) => this.owns(key)) }),
      }
    })
  }

  put(path: string, entry: IndexEntry): Promise<void> {
    return withCacheMutation(this.cache, async () => {
      if (this.owns(path)) await this.store.put(path, entry)
    })
  }

  setDir(
    path: string,
    entries: readonly [string, IndexEntry][],
    expiredAt?: Date | null,
  ): Promise<void> {
    return this.storeDir(path, entries, expiredAt, false)
  }

  override setPartialDir(
    path: string,
    entries: readonly [string, IndexEntry][],
    expiredAt?: Date | null,
  ): Promise<void> {
    return this.storeDir(path, entries, expiredAt, true)
  }

  private storeDir(
    path: string,
    entries: readonly [string, IndexEntry][],
    expiredAt: Date | null | undefined,
    partial: boolean,
  ): Promise<void> {
    return withCacheMutation(this.cache, async () => {
      if (this.owns(path)) {
        const prefix = rstripSlash(path) + '/'
        const owned = entries.filter(([name]) => this.owns(prefix + name))
        if (partial) await this.store.setPartialDir(path, owned, expiredAt)
        else await this.store.setDir(path, owned, expiredAt)
      }
    })
  }

  invalidateDir(path: string): Promise<void> {
    return withCacheMutation(this.cache, async () => {
      if (this.owns(path)) await this.store.invalidateDir(path)
    })
  }

  invalidatePrefix(path: string): Promise<void> {
    return withCacheMutation(this.cache, async () => {
      if (this.owns(path)) await this.store.invalidatePrefix(path)
    })
  }

  invalidate(): Promise<void> {
    return withCacheMutation(this.cache, async () => {
      if (this.owns(this.prefix)) await this.store.invalidate()
    })
  }

  clear(): Promise<void> {
    return this.invalidatePrefix(this.prefix)
  }
}
