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

import { toIsoZ } from '../../utils/dates.ts'
import { KeyLock } from '../lock.ts'
import { uuid7 } from '../../utils/ids.ts'
import { loadOptionalPeer } from '../../utils/optional_peer.ts'
import { rstripSlash } from '../../utils/slash.ts'
import {
  IndexDirectorySchema,
  IndexEntry,
  LookupStatus,
  type Evicted,
  type IndexDirectory,
  type ListResult,
  type LookupResult,
  type SetDirOptions,
} from './config.ts'
import { IndexCacheStore } from './store.ts'
import {
  CHILDREN_PREFIX,
  DEFAULT_KEY_PREFIX,
  ENTRY_PREFIX,
  GENERATION_KEY,
  PATHS_KEY,
  TOMBSTONE_PREFIX,
} from './constants.ts'

// Redis can evict the registry independently of its indexed paths.
const PATH_REGISTRY = `
local function track(registry, prefixes, paths)
  if not redis.call('ZSCORE', registry, '') then
    local cursor = '0'
    repeat
      local batch = redis.call('SCAN', cursor, 'COUNT', 1000)
      cursor = batch[1]
      for _, key in ipairs(batch[2]) do
        for _, prefix in ipairs(prefixes) do
          if string.sub(key, 1, #prefix) == prefix then
            redis.call('ZADD', registry, 0, string.sub(key, #prefix + 1))
            break
          end
        end
      end
    until cursor == '0'
    redis.call('ZADD', registry, 0, '')
  end
  for _, path in ipairs(paths) do redis.call('ZADD', registry, 0, path) end
end
local function prune(registry, prefixes, path)
  for _, prefix in ipairs(prefixes) do
    if redis.call('EXISTS', prefix .. path) == 1 then return end
  end
  redis.call('ZREM', registry, path)
end
local function subtree(registry, root)
  root = string.gsub(root, '/+$', '')
  if root == '' then root = '/' end
  local lower = root == '/' and '/' or root .. '/'
  local upper = root == '/' and '0' or root .. '0'
  local paths = redis.call('ZRANGEBYLEX', registry, '[' .. lower, '(' .. upper)
  paths[#paths + 1] = root
  return paths
end
`

const TRACK_PATHS =
  PATH_REGISTRY +
  `
local paths = {}
for i = 5, #ARGV do paths[#paths + 1] = ARGV[i] end
track(KEYS[1], {ARGV[1], ARGV[2], ARGV[3], ARGV[4]}, paths)
return 1
`

const DELETE_PATHS =
  PATH_REGISTRY +
  `
local prefixes = {ARGV[1], ARGV[2], ARGV[3], ARGV[4]}
track(KEYS[1], prefixes, {})
local excluded = cjson.decode(ARGV[7])
for _, path in ipairs(subtree(KEYS[1], ARGV[6])) do
  local protected = false
  for _, root in ipairs(excluded) do
    if path == root or string.sub(path, 1, #root + 1) == root .. '/' then
      protected = true
      break
    end
  end
  if not protected then
    redis.call('DEL', ARGV[5] .. path)
    prune(KEYS[1], prefixes, path)
  end
end
`

const DELETE_ENTRY =
  PATH_REGISTRY +
  `
local prefixes = {ARGV[1], ARGV[2], ARGV[3], ARGV[4]}
track(KEYS[1], prefixes, {})
redis.call('DEL', ARGV[1] .. ARGV[5])
prune(KEYS[1], prefixes, ARGV[5])
`

const SWAP_LISTING =
  PATH_REGISTRY +
  `
track(KEYS[3], {ARGV[2], ARGV[3], ARGV[4], ARGV[5]},
  {string.sub(KEYS[1], #ARGV[3] + 1)})
local old = redis.call('GET', KEYS[1])
local tomb = redis.call('GET', KEYS[2])
redis.call('DEL', KEYS[2])
local excluded = cjson.decode(ARGV[6])
local function protected(path)
  for _, prefix in ipairs(excluded) do
    if path == prefix or string.sub(path, 1, #prefix + 1) == prefix .. '/' then
      return true
    end
  end
  return false
end
local named = {}
for i = 7, #ARGV, 2 do
  named[ARGV[i]] = cjson.decode(ARGV[i + 1]).resource_type
end
local seen, gone, folders = {}, {}, {}
local function drop(path, buried)
  if seen[path] or protected(path) then
    return
  end
  local row = redis.call('GET', ARGV[2] .. path)
  local folder = buried or redis.call('EXISTS', ARGV[3] .. path) == 1
    or (row ~= false and cjson.decode(row).resource_type == 'folder')
  if named[path] and not (folder and named[path] ~= 'folder') then
    return
  end
  seen[path] = true
  redis.call('DEL', ARGV[2] .. path)
  prune(KEYS[3], {ARGV[2], ARGV[3], ARGV[4], ARGV[5]}, path)
  gone[#gone + 1] = path
  folders[#folders + 1] = folder and 1 or 0
end
if old then
  for _, path in ipairs(cjson.decode(old).entries) do
    drop(path, false)
  end
end
if tomb then
  local t = cjson.decode(tomb)
  for i, path in ipairs(t.entries) do
    drop(path, t.folders[i] == 1)
  end
end
for i = 7, #ARGV, 2 do drop(ARGV[i], false) end
local roots = {}
for i, path in ipairs(gone) do
  if folders[i] == 1 then roots[#roots + 1] = path end
end
local function remove(path)
  if protected(path) then return end
  for _, prefix in ipairs({ARGV[2], ARGV[3], ARGV[4], ARGV[5]}) do
    redis.call('DEL', prefix .. path)
  end
  redis.call('ZREM', KEYS[3], path)
end
for _, root in ipairs(roots) do
  for _, path in ipairs(subtree(KEYS[3], root)) do remove(path) end
end
for i = 7, #ARGV, 2 do
  redis.call('SET', ARGV[2] .. ARGV[i], ARGV[i + 1])
  redis.call('ZADD', KEYS[3], 0, ARGV[i])
end
redis.call('SET', KEYS[1], ARGV[1])
return {gone, folders}
`

const BURY_LISTING =
  PATH_REGISTRY +
  `
track(KEYS[4], {ARGV[1], ARGV[2], ARGV[3], ARGV[4]},
  {string.sub(KEYS[1], #ARGV[2] + 1)})
local raw = redis.call('GET', KEYS[1])
if raw then
  local entries = cjson.decode(raw).entries
  local folders = {}
  for i, path in ipairs(entries) do
    local row = redis.call('GET', ARGV[1] .. path)
    local folder = redis.call('EXISTS', ARGV[2] .. path) == 1
      or (row ~= false and cjson.decode(row).resource_type == 'folder')
    folders[i] = folder and 1 or 0
    redis.call('DEL', ARGV[1] .. path)
    prune(KEYS[4], {ARGV[1], ARGV[2], ARGV[3], ARGV[4]}, path)
  end
  redis.call('SET', KEYS[2],
    cjson.encode({entries = entries, folders = folders}))
end
redis.call('DEL', KEYS[1])
redis.call('DEL', KEYS[3])
prune(KEYS[4], {ARGV[1], ARGV[2], ARGV[3], ARGV[4]},
  string.sub(KEYS[1], #ARGV[2] + 1))
`

/**
 * Escape redis MATCH metacharacters in a literal path.
 *
 * A path may legally contain `*?[]`, and SCAN's pattern is a glob, so an
 * unescaped path would match keys it does not name. The escaping is a
 * narrowing optimization only; the caller still filters at a path boundary.
 * Mirrors Python `_glob_escape` (`cache/index/redis.py`).
 */
function globEscape(value: string): string {
  return value.replace(/[*?[\]\\]/g, (char) => `\\${char}`)
}

interface RedisPipeline {
  eval: (script: string, options: { keys: string[]; arguments: string[] }) => RedisPipeline
  set: (key: string, value: string, options?: { NX: boolean }) => RedisPipeline
  del: (key: string) => RedisPipeline
  exec: () => Promise<unknown>
}

export interface RedisClientLike {
  connect: () => Promise<unknown>
  get: (key: string) => Promise<string | null>
  mGet: (keys: string[]) => Promise<(string | null)[]>
  set: (key: string, value: string, options?: { NX: boolean }) => Promise<unknown>
  del: (key: string | string[]) => Promise<unknown>
  multi: () => RedisPipeline
  eval: (script: string, options: { keys: string[]; arguments: string[] }) => Promise<unknown>
  exists: (key: string) => Promise<number>
  scanIterator: (options: { MATCH: string }) => AsyncIterable<string | string[]>
  isOpen: boolean
  quit: () => Promise<unknown>
}

export interface RedisIndexCacheOptions {
  ttl?: number
  url?: string
  client?: RedisClientLike
  keyPrefix?: string
}

// Directory records retain stale listings like RAM; Redis maxmemory eviction
// can still turn any cached fact into a miss. A missing path registry is rebuilt
// with one database scan; ordinary eviction visits only the removed subtrees.
export class RedisIndexCacheStore extends IndexCacheStore {
  readonly ttl: number
  private readonly url: string
  private readonly providedClient: RedisClientLike | null
  private readonly entryPrefix: string
  private readonly childrenPrefix: string
  private readonly tombstonePrefix: string
  private readonly pathsKey: string
  private readonly generationKey: string
  private readonly initializingGenerations = new Map<string, Promise<string>>()
  private clientPromise: Promise<RedisClientLike> | null = null

  private readonly seedLock = new KeyLock()
  private readonly pendingSeeds: {
    entries: Map<string, IndexEntry>
    children: Map<string, string[]>
    expiresAt: number
  }[] = []
  private closed = false

  constructor(options: RedisIndexCacheOptions = {}) {
    super()
    this.ttl = options.ttl ?? 600
    this.url = options.url ?? 'redis://localhost:6379/0'
    this.providedClient = options.client ?? null
    const prefix = options.keyPrefix ?? DEFAULT_KEY_PREFIX
    this.entryPrefix = `${prefix}${ENTRY_PREFIX}`
    this.childrenPrefix = `${prefix}${CHILDREN_PREFIX}`
    this.tombstonePrefix = `${prefix}${TOMBSTONE_PREFIX}`
    this.generationKey = `${prefix}${GENERATION_KEY}`
    this.pathsKey = `${prefix}${PATHS_KEY}`
  }

  private entryKey(path: string): string {
    return `${this.entryPrefix}${path}`
  }

  private childrenKey(path: string): string {
    return `${this.childrenPrefix}${path}`
  }

  private client(): Promise<RedisClientLike> {
    if (this.providedClient !== null) return Promise.resolve(this.providedClient)
    this.clientPromise ??= (async () => {
      const spec = 'redis'
      const mod = (await loadOptionalPeer(() => import(/* @vite-ignore */ spec), {
        feature: 'RedisIndexCacheStore',
        packageName: 'redis',
      })) as {
        createClient: (o: { url: string; socket?: unknown }) => RedisClientLike
      }
      const c = mod.createClient({
        url: this.url,
        socket: { reconnectStrategy: false },
      })
      await c.connect()
      return c
    })()
    return this.clientPromise
  }

  seed(
    entries: ReadonlyMap<string, IndexEntry>,
    children: ReadonlyMap<string, readonly string[]>,
    expiresAt: Date,
  ): void {
    const nowIso = toIsoZ(new Date())
    this.pendingSeeds.push({
      entries: new Map(
        [...entries].map(([path, entry]) => [
          path,
          entry.indexTime === '' ? entry.copyWith({ indexTime: nowIso }) : entry,
        ]),
      ),
      children: new Map([...children].map(([path, keys]) => [path, [...keys]])),
      expiresAt: expiresAt.getTime() / 1000,
    })
  }

  private trackPaths(pipe: RedisPipeline, paths: readonly string[]): void {
    pipe.eval(TRACK_PATHS, {
      keys: [this.pathsKey],
      arguments: [
        this.entryPrefix,
        this.childrenPrefix,
        this.tombstonePrefix,
        `${this.generationKey}:`,
        ...paths,
      ],
    })
  }

  private generation(c: RedisClientLike, key: string): Promise<string> {
    const pending = this.initializingGenerations.get(key)
    if (pending !== undefined) return pending
    // Parallel directory refills in this store share one global initializer.
    // Do not retain it afterwards: the next read must observe invalidations.
    const initialized = (async () => {
      const current = await c.get(key)
      if (current !== null) return current
      // A new token after eviction must never revive an old listing.
      const generation = uuid7()
      if (key === this.generationKey) {
        await c.set(key, generation, { NX: true })
      } else {
        const pipe = c.multi()
        this.trackPaths(pipe, [key.slice(this.generationKey.length + 1)])
        pipe.set(key, generation, { NX: true })
        await pipe.exec()
      }
      // Even when NX loses, keep our attempted token. A later read could adopt
      // a replacement written by an invalidation/refill and revive old data.
      return generation
    })().finally(() => {
      this.initializingGenerations.delete(key)
    })
    this.initializingGenerations.set(key, initialized)
    return initialized
  }

  private flushSeed(): Promise<void> {
    return this.seedLock.withLock('seed', async () => {
      while (this.pendingSeeds.length > 0) {
        const pending = [...this.pendingSeeds]
        const c = await this.client()
        const generation = await this.generation(c, this.generationKey)
        const directories = new Map<string, string>()
        const paths = [...new Set(pending.flatMap((seed) => [...seed.children.keys()]))]
        if (paths.length > 0) {
          const current = await c.mGet(paths.map((path) => `${this.generationKey}:${path}`))
          const missing = new Map<string, string>()
          // Keep observed tokens: rereading them after a concurrent invalidation
          // could stamp the pending snapshot with a replacement generation.
          for (const [i, path] of paths.entries()) {
            const token = current[i]
            if (token == null) missing.set(path, uuid7())
            else directories.set(path, token)
          }
          if (missing.size > 0) {
            const initialize = c.multi()
            this.trackPaths(initialize, [...missing.keys()])
            for (const [path, token] of missing) {
              initialize.set(`${this.generationKey}:${path}`, token, { NX: true })
            }
            await initialize.exec()
            for (const [path, token] of missing) directories.set(path, token)
          }
        }
        const pipe = c.multi()
        this.trackPaths(
          pipe,
          pending.flatMap((seed) => [...seed.entries.keys(), ...seed.children.keys()]),
        )
        for (const seed of pending) {
          for (const [path, entry] of seed.entries) {
            pipe.set(this.entryKey(path), JSON.stringify(entry))
          }
          for (const [path, keys] of seed.children) {
            const listing: IndexDirectory = {
              entries: keys,
              expires_at: seed.expiresAt,
              generation: `${generation}:${directories.get(path) ?? ''}`,
              partial: false,
            }
            pipe.set(this.childrenKey(path), JSON.stringify(listing))
          }
        }
        await pipe.exec()
        this.pendingSeeds.splice(0, pending.length)
      }
    })
  }

  async entries(): Promise<Map<string, IndexEntry>> {
    await this.flushSeed()
    const c = await this.client()
    const entries = new Map<string, IndexEntry>()
    for await (const batch of c.scanIterator({ MATCH: `${globEscape(this.entryPrefix)}*` })) {
      for (const key of Array.isArray(batch) ? batch : [batch]) {
        const raw = await c.get(key)
        if (raw !== null) entries.set(key.slice(this.entryPrefix.length), IndexEntry.fromJSON(raw))
      }
    }
    return entries
  }

  async get(vfsPath: string): Promise<LookupResult> {
    await this.flushSeed()
    const c = await this.client()
    const raw = await c.get(this.entryKey(vfsPath))
    if (raw === null) return { status: LookupStatus.NOT_FOUND }
    return { entry: IndexEntry.fromJSON(raw) }
  }

  async put(vfsPath: string, entry: IndexEntry): Promise<void> {
    await this.flushSeed()
    const c = await this.client()
    const stored =
      entry.indexTime === '' ? entry.copyWith({ indexTime: toIsoZ(new Date()) }) : entry
    const pipe = c.multi()
    this.trackPaths(pipe, [vfsPath])
    pipe.set(this.entryKey(vfsPath), JSON.stringify(stored))
    await pipe.exec()
  }

  async listDir(vfsPath: string): Promise<ListResult> {
    await this.flushSeed()
    const c = await this.client()
    const [raw, current, directory] = await c.mGet([
      this.childrenKey(vfsPath),
      this.generationKey,
      `${this.generationKey}:${vfsPath}`,
    ])
    if (raw == null) return { status: LookupStatus.NOT_FOUND }
    const listing = IndexDirectorySchema.parse(JSON.parse(raw))
    if (
      current == null ||
      directory == null ||
      listing.generation !== `${current}:${directory}` ||
      Date.now() / 1000 >= listing.expires_at
    )
      return { status: LookupStatus.EXPIRED }
    return listing.partial ? { partialEntries: listing.entries } : { entries: listing.entries }
  }

  async setDir(
    vfsPath: string,
    entries: readonly [string, IndexEntry][],
    expiredAt?: Date | null,
    options: SetDirOptions = {},
  ): Promise<Evicted[]> {
    return this.storeDir(
      vfsPath,
      entries,
      expiredAt,
      false,
      options.window !== true,
      options.excluded ?? [],
    )
  }

  override async setPartialDir(
    vfsPath: string,
    entries: readonly [string, IndexEntry][],
    expiredAt?: Date | null,
  ): Promise<void> {
    await this.storeDir(vfsPath, entries, expiredAt, true, false)
  }

  private async storeDir(
    vfsPath: string,
    entries: readonly [string, IndexEntry][],
    expiredAt: Date | null | undefined,
    partial: boolean,
    evict: boolean,
    excluded: readonly string[] = [],
  ): Promise<Evicted[]> {
    await this.flushSeed()
    const c = await this.client()
    const now = new Date()
    const nowIso = toIsoZ(now)
    const prefix = vfsPath === '/' ? '/' : `${vfsPath}/`
    const generation = await this.generation(c, this.generationKey)
    const directory = await this.generation(c, `${this.generationKey}:${vfsPath}`)
    const rows: [string, string][] = []
    for (const [name, entry] of entries) {
      const stored = entry.indexTime === '' ? entry.copyWith({ indexTime: nowIso }) : entry
      rows.push([prefix + name, JSON.stringify(stored)])
    }
    const listing: IndexDirectory = {
      entries: rows.map(([path]) => path),
      generation: `${generation}:${directory}`,
      expires_at: (expiredAt?.getTime() ?? now.getTime() + this.ttl * 1000) / 1000,
      partial,
    }
    if (!evict) {
      const pipe = c.multi()
      this.trackPaths(pipe, [vfsPath, ...rows.map(([path]) => path)])
      for (const [path, row] of rows) pipe.set(this.entryKey(path), row)
      pipe.set(this.childrenKey(vfsPath), JSON.stringify(listing))
      // A window is the new full knowledge; it proves nothing gone and leaves
      // nothing for a later listing to diff against.
      if (!partial) pipe.del(this.tombstonePrefix + vfsPath)
      await pipe.exec()
      return []
    }
    // One script, so no other writer lands between reading the previous
    // listing and replacing it; the diff is against the true predecessor.
    const [gone, folders] = (await c.eval(SWAP_LISTING, {
      keys: [this.childrenKey(vfsPath), this.tombstonePrefix + vfsPath, this.pathsKey],
      arguments: [
        JSON.stringify(listing),
        this.entryPrefix,
        this.childrenPrefix,
        this.tombstonePrefix,
        `${this.generationKey}:`,
        JSON.stringify(excluded.map(rstripSlash)),
        ...rows.flat(),
      ],
    })) as [string[], number[]]
    const dropped: Evicted[] = []
    for (const [i, path] of gone.entries()) {
      dropped.push({ path, folder: folders[i] === 1 })
    }
    return dropped
  }

  async invalidateEntry(vfsPath: string): Promise<void> {
    await this.flushSeed()
    const c = await this.client()
    await c.eval(DELETE_ENTRY, {
      keys: [this.pathsKey],
      arguments: [
        this.entryPrefix,
        this.childrenPrefix,
        this.tombstonePrefix,
        `${this.generationKey}:`,
        vfsPath,
      ],
    })
  }

  async invalidateDir(vfsPath: string): Promise<void> {
    await this.flushSeed()
    const c = await this.client()
    // The child list becomes a tombstone, so the next complete listing can
    // still tell which children went away.
    await c.eval(BURY_LISTING, {
      keys: [
        this.childrenKey(vfsPath),
        this.tombstonePrefix + vfsPath,
        `${this.generationKey}:${vfsPath}`,
        this.pathsKey,
      ],
      arguments: [
        this.entryPrefix,
        this.childrenPrefix,
        this.tombstonePrefix,
        `${this.generationKey}:`,
      ],
    })
  }

  private async deletePaths(
    prefix: string,
    vfsPath: string,
    excluded: readonly string[] = [],
  ): Promise<void> {
    const c = await this.client()
    await c.eval(DELETE_PATHS, {
      keys: [this.pathsKey],
      arguments: [
        this.entryPrefix,
        this.childrenPrefix,
        this.tombstonePrefix,
        `${this.generationKey}:`,
        prefix,
        vfsPath,
        JSON.stringify(excluded.map(rstripSlash)),
      ],
    })
  }

  async invalidatePrefix(vfsPath: string, excluded: readonly string[] = []): Promise<void> {
    await this.flushSeed()
    await this.deletePaths(this.entryPrefix, vfsPath, excluded)
    await this.deletePaths(this.childrenPrefix, vfsPath, excluded)
    await this.deletePaths(`${this.generationKey}:`, vfsPath, excluded)
  }

  async invalidate(): Promise<void> {
    await this.flushSeed()
    const c = await this.client()
    // Atomically expire listings without overwriting concurrent refills/deletions.
    await c.set(this.generationKey, uuid7())
  }

  clear(): Promise<void> {
    return this.seedLock.withLock('seed', async () => {
      this.pendingSeeds.length = 0
      await this.deletePaths(this.entryPrefix, '/')
      await this.deletePaths(this.childrenPrefix, '/')
      await this.deletePaths(this.tombstonePrefix, '/')
      await this.deletePaths(`${this.generationKey}:`, '/')
      const c = await this.client()
      await c.del([this.generationKey, this.pathsKey])
    })
  }

  override async close(): Promise<void> {
    if (this.closed) return
    await this.flushSeed()
    if (this.providedClient === null && this.clientPromise !== null) {
      const c = await this.clientPromise
      const typed = c as unknown as { destroy?: () => void }
      if (typeof typed.destroy === 'function') typed.destroy()
      else if (c.isOpen) await c.quit()
      this.clientPromise = null
    }
    this.closed = true
  }
}
