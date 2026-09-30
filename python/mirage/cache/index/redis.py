# ========= Copyright 2026 @ Strukto.AI All Rights Reserved. =========
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ========= Copyright 2026 @ Strukto.AI All Rights Reserved. =========

import asyncio
import json
from collections.abc import Awaitable
from datetime import datetime, timedelta, timezone
from typing import cast

try:
    from redis.asyncio import Redis
except ImportError as _err:
    raise ImportError("RedisIndexCacheStore requires the 'redis' extra. "
                      "Install with: pip install mirage-ai[redis]") from _err

from mirage.cache.index.config import (Evicted, IndexDirectory, IndexEntry,
                                       ListResult, LookupResult, LookupStatus)
from mirage.cache.index.constants import (CHILDREN_PREFIX, ENTRY_PREFIX,
                                          GENERATION_KEY, TOMBSTONE_PREFIX)
from mirage.cache.index.store import IndexCacheStore
from mirage.core.timeutil import to_iso_z
from mirage.utils.ids import uuid7
from mirage.utils.key_prefix import under_path


def _text(value: str | bytes) -> str:
    return value.decode() if isinstance(value, bytes) else value


_SWAP_LISTING = """
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
local roots = {}
for i, path in ipairs(gone) do
  if folders[i] == 1 then roots[#roots + 1] = path end
end
if #roots > 0 then
  local cursor, doomed = '0', {}
  repeat
    local batch = redis.call('SCAN', cursor, 'COUNT', 1000)
    cursor = batch[1]
    for _, key in ipairs(batch[2]) do
      for _, prefix in ipairs({ARGV[2], ARGV[3], ARGV[4], ARGV[5]}) do
        if string.sub(key, 1, #prefix) == prefix then
          local path = string.sub(key, #prefix + 1)
          for _, root in ipairs(roots) do
            if not protected(path) and (path == root
              or string.sub(path, 1, #root + 1) == root .. '/') then
              doomed[#doomed + 1] = key
              break
            end
          end
          break
        end
      end
    end
  until cursor == '0'
  for _, key in ipairs(doomed) do redis.call('DEL', key) end
end
for i = 7, #ARGV, 2 do
  redis.call('SET', ARGV[2] .. ARGV[i], ARGV[i + 1])
end
redis.call('SET', KEYS[1], ARGV[1])
return {gone, folders}
"""

_BURY_LISTING = """
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
  end
  redis.call('SET', KEYS[2],
    cjson.encode({entries = entries, folders = folders}))
end
redis.call('DEL', KEYS[1])
redis.call('DEL', KEYS[3])
"""


def _glob_escape(value: str) -> str:
    """Escape redis MATCH metacharacters in a literal path.

    A path may legally contain ``*?[]``, and SCAN's pattern is a glob, so
    an unescaped path would match keys it does not name. The escaping is
    a narrowing optimization only; the caller still filters the results
    at a path boundary.

    Args:
        value (str): A literal path to embed in a MATCH pattern.
    """
    out: list[str] = []
    for char in value:
        if char in "*?[]\\":
            out.append("\\")
        out.append(char)
    return "".join(out)


class RedisIndexCacheStore(IndexCacheStore):
    """Redis-backed index cache for remote VFS metadata.

    Stores IndexEntry objects as JSON strings and directory children as
    JSON records holding children and expiry, including empty listings.
    Like RAM, stale records remain until explicitly cleared or invalidated by
    path, so expiry is distinguishable from absence. Redis eviction may still
    remove records; size limits belong to the server, not this store.
    All writes within set_dir are batched in a single pipeline for efficiency.

    Multiple stores can share one Redis server by using distinct key_prefix
    values (e.g. "gdrive:", "s3:"). The full key layout is::

        {key_prefix}mirage:idx:entry:{vfs_path} -> IndexEntry JSON
        {key_prefix}mirage:idx:directory:{vfs_path} -> IndexDirectory JSON

    Args:
        ttl (float): Default time-to-live in seconds for directory listings.
        url (str): Redis connection URL, used when *client* is not provided.
        client (Redis | None): Pre-existing async Redis client. When given,
            the store will not close it on ``close()``.
        key_prefix (str): Namespace prefix prepended to every Redis key,
            allowing multiple stores to coexist on the same server.
    """

    def __init__(
        self,
        ttl: float = 600,
        url: str = "redis://localhost:6379/0",
        client: Redis | None = None,
        key_prefix: str = "",
    ) -> None:
        super().__init__()
        self._ttl = ttl
        self._client = (client if client is not None else Redis.from_url(
            url, decode_responses=True))
        self._owns_client = client is None
        self._pending_seeds: list[tuple[dict[str, IndexEntry],
                                        dict[str, list[str]], datetime]] = []
        self._seed_lock = asyncio.Lock()
        self._generation_tasks: dict[str, asyncio.Task[str]] = {}
        p = key_prefix or ""
        self._entry_prefix = f"{p}{ENTRY_PREFIX}"
        self._children_prefix = f"{p}{CHILDREN_PREFIX}"
        self._tombstone_prefix = f"{p}{TOMBSTONE_PREFIX}"
        self._generation_key = f"{p}{GENERATION_KEY}"
        self._directory_generation_prefix = f"{self._generation_key}:"

    def _entry_key(self, vfs_path: str) -> str:
        return f"{self._entry_prefix}{vfs_path}"

    def _children_key(self, vfs_path: str) -> str:
        return f"{self._children_prefix}{vfs_path}"

    def seed(self, entries: dict[str, IndexEntry],
             children: dict[str, list[str]], expires_at: datetime) -> None:
        now_iso = to_iso_z(datetime.now(timezone.utc))
        self._pending_seeds.append(({
            path:
            entry if entry.index_time else entry.model_copy(
                update={"index_time": now_iso})
            for path, entry in entries.items()
        }, {
            path: list(keys)
            for path, keys in children.items()
        }, expires_at))

    async def _generation(self, key: str) -> str:
        task = self._generation_tasks.get(key)
        if task is None or task.done():

            async def initialize() -> str:
                current = await self._client.get(key)
                if current is not None:
                    return _text(current)
                generation = uuid7()
                await self._client.set(key, generation, nx=True)
                # Never adopt a later token: a concurrent invalidation may
                # have replaced it. Losing safely costs one extra refill.
                return generation

            def finished(completed: asyncio.Task[str]) -> None:
                if self._generation_tasks.get(key) is completed:
                    self._generation_tasks.pop(key, None)
                # Retrieve failures even if every waiter was cancelled.
                if not completed.cancelled():
                    completed.exception()

            task = asyncio.create_task(initialize())
            self._generation_tasks[key] = task
            task.add_done_callback(finished)
        # Parallel directory writes in one store share token initialization;
        # cancellation of one waiter must not cancel the others.
        return await asyncio.shield(task)

    async def _directory_generations(self,
                                     directories: set[str]) -> dict[str, str]:
        if not directories:
            return {}
        paths = list(directories)
        keys = [f"{self._directory_generation_prefix}{path}" for path in paths]
        current = await self._client.mget(keys)
        generations = {
            path: _text(token)
            for path, token in zip(paths, current) if token is not None
        }
        missing = {path: uuid7() for path in paths if path not in generations}
        if missing:
            pipe = self._client.pipeline()
            for path, token in missing.items():
                pipe.set(f"{self._directory_generation_prefix}{path}",
                         token,
                         nx=True)
            await pipe.execute()
            generations.update(missing)
        # Keep observed or attempted tokens, including failed NX attempts:
        # rereading could adopt a token created after an invalidation.
        return generations

    async def _flush_seed(self) -> None:
        async with self._seed_lock:
            while self._pending_seeds:
                pending = list(self._pending_seeds)
                generation = await self._generation(self._generation_key)
                directories = {
                    path
                    for _, children, _ in pending
                    for path in children
                }
                directory_generations = await self._directory_generations(
                    directories)
                pipe = self._client.pipeline()
                for entries, children, expires_at in pending:
                    for vfs_path, entry in entries.items():
                        pipe.set(self._entry_key(vfs_path),
                                 entry.model_dump_json())
                    for vfs_path, child_keys in children.items():
                        listing = IndexDirectory(
                            entries=child_keys,
                            expires_at=expires_at.timestamp(),
                            generation=
                            f"{generation}:{directory_generations[vfs_path]}")
                        pipe.set(self._children_key(vfs_path),
                                 listing.model_dump_json())
                await pipe.execute()
                del self._pending_seeds[:len(pending)]

    @property
    def ttl(self) -> float:
        return self._ttl

    async def get(self, vfs_path: str) -> LookupResult:
        await self._flush_seed()
        raw = await self._client.get(self._entry_key(vfs_path))
        if raw is None:
            return LookupResult(status=LookupStatus.NOT_FOUND)
        entry = IndexEntry.model_validate_json(raw)
        return LookupResult(entry=entry)

    async def put(self, vfs_path: str, entry: IndexEntry) -> None:
        await self._flush_seed()
        if not entry.index_time:
            entry = entry.model_copy(
                update={"index_time": to_iso_z(datetime.now(timezone.utc))})
        await self._client.set(self._entry_key(vfs_path),
                               entry.model_dump_json())

    async def list_dir(self, vfs_path: str) -> ListResult:
        await self._flush_seed()
        key = self._children_key(vfs_path)
        raw, current, directory = await self._client.mget(
            key, self._generation_key,
            f"{self._directory_generation_prefix}{vfs_path}")
        if raw is None:
            return ListResult(status=LookupStatus.NOT_FOUND)
        listing = IndexDirectory.model_validate_json(raw)
        if (current is None or directory is None
                or listing.generation != f"{_text(current)}:{_text(directory)}"
                or datetime.now(
                    timezone.utc).timestamp() >= listing.expires_at):
            return ListResult(status=LookupStatus.EXPIRED)
        if listing.partial:
            return ListResult(partial_entries=listing.entries)
        return ListResult(entries=listing.entries)

    async def set_dir(
            self,
            vfs_path: str,
            entries: list[tuple[str, IndexEntry]],
            expired_at: datetime | None = None,
            *,
            window: bool = False,
            excluded: tuple[str, ...] = (),
    ) -> list[Evicted]:
        return await self._set_dir(vfs_path,
                                   entries,
                                   expired_at,
                                   partial=False,
                                   evict=not window,
                                   excluded=excluded)

    async def set_partial_dir(
        self,
        vfs_path: str,
        entries: list[tuple[str, IndexEntry]],
        expired_at: datetime | None = None,
    ) -> None:
        await self._set_dir(vfs_path,
                            entries,
                            expired_at,
                            partial=True,
                            evict=False)

    async def _set_dir(
            self,
            vfs_path: str,
            entries: list[tuple[str, IndexEntry]],
            expired_at: datetime | None,
            *,
            partial: bool,
            evict: bool,
            excluded: tuple[str, ...] = (),
    ) -> list[Evicted]:
        await self._flush_seed()
        now = datetime.now(timezone.utc)
        now_iso = to_iso_z(now)
        prefix = "/" if vfs_path == "/" else vfs_path + "/"

        generation = await self._generation(self._generation_key)
        directory_generation = await self._generation(
            f"{self._directory_generation_prefix}{vfs_path}")
        rows: list[tuple[str, str]] = []
        for name, entry in entries:
            if not entry.index_time:
                entry = entry.model_copy(update={"index_time": now_iso})
            rows.append((prefix + name, entry.model_dump_json()))

        expiry = expired_at if expired_at is not None else now + timedelta(
            seconds=self._ttl)
        listing = IndexDirectory(
            entries=[path for path, _ in rows],
            expires_at=expiry.timestamp(),
            generation=f"{generation}:{directory_generation}",
            partial=partial)
        if not evict:
            pipe = self._client.pipeline()
            for path, row in rows:
                pipe.set(self._entry_key(path), row)
            pipe.set(self._children_key(vfs_path), listing.model_dump_json())
            if not partial:
                # A window is the new full knowledge; it proves nothing gone
                # and leaves nothing for a later listing to diff against.
                pipe.delete(self._tombstone_prefix + vfs_path)
            await pipe.execute()
            return []
        # One script, so no other writer lands between reading the previous
        # listing and replacing it; the diff is against the true predecessor.
        gone, folders = await cast(
            Awaitable[tuple[list[str | bytes], list[int]]],
            self._client.eval(_SWAP_LISTING, 2, self._children_key(vfs_path),
                              self._tombstone_prefix + vfs_path,
                              listing.model_dump_json(), self._entry_prefix,
                              self._children_prefix, self._tombstone_prefix,
                              self._directory_generation_prefix,
                              json.dumps([p.rstrip("/") for p in excluded]),
                              *(value for row in rows for value in row)))
        dropped: list[Evicted] = []
        for raw, flag in zip(gone, folders):
            key = _text(raw)
            dropped.append(Evicted(key, folder=bool(flag)))
        return dropped

    async def entries(self) -> dict[str, IndexEntry]:
        await self._flush_seed()
        entries: dict[str, IndexEntry] = {}
        cursor = 0
        while True:
            cursor, keys = await self._client.scan(
                cursor,
                match=f"{_glob_escape(self._entry_prefix)}*",
                count=500)
            for key in keys:
                key_text = _text(key)
                raw = await self._client.get(key)
                if raw is not None:
                    vfs_path = key_text.removeprefix(self._entry_prefix)
                    entries[vfs_path] = IndexEntry.model_validate_json(raw)
            if cursor == 0:
                return entries

    async def invalidate_entry(self, vfs_path: str) -> None:
        await self._flush_seed()
        await self._client.delete(self._entry_key(vfs_path))

    async def invalidate_dir(self, vfs_path: str) -> None:
        await self._flush_seed()
        # The child list becomes a tombstone, so the next complete listing
        # can still tell which children went away.
        await cast(
            Awaitable[None],
            self._client.eval(
                _BURY_LISTING, 3, self._children_key(vfs_path),
                self._tombstone_prefix + vfs_path,
                f"{self._directory_generation_prefix}{vfs_path}",
                self._entry_prefix, self._children_prefix))

    async def _scan_delete(
        self, prefix: str, vfs_path: str, excluded: tuple[str,
                                                          ...] = ()) -> None:
        """Delete every key under ``prefix`` naming a path in the subtree.

        Args:
            prefix (str): Key namespace to scan (entries or children).
            vfs_path (str): Mount-absolute root of the subtree.
            excluded (tuple[str, ...]): nested mount roots to preserve.
        """
        pattern = f"{_glob_escape(prefix + vfs_path.rstrip('/'))}*"
        cursor = 0
        while True:
            cursor, keys = await self._client.scan(cursor,
                                                   match=pattern,
                                                   count=500)
            doomed = [
                key for key in keys
                if under_path(_text(key).removeprefix(prefix), vfs_path)
                and not any(
                    under_path(_text(key).removeprefix(prefix), p)
                    for p in excluded)
            ]
            if doomed:
                await self._client.delete(*doomed)
            if cursor == 0:
                return

    async def invalidate_prefix(self,
                                vfs_path: str,
                                *,
                                excluded: tuple[str, ...] = ()) -> None:
        await self._flush_seed()
        await self._scan_delete(self._entry_prefix, vfs_path, excluded)
        # Forgetting what is cached is not evidence that anything went
        # away, so tombstones survive for the next complete listing.
        await self._scan_delete(self._children_prefix, vfs_path, excluded)
        await self._scan_delete(self._directory_generation_prefix, vfs_path,
                                excluded)

    async def invalidate(self) -> None:
        await self._flush_seed()
        # One atomic generation change expires all listings without racing
        # another client's refill or resurrecting a concurrently removed path.
        await self._client.set(self._generation_key, uuid7())

    async def clear(self) -> None:
        async with self._seed_lock:
            self._pending_seeds.clear()
            await self._scan_delete(self._entry_prefix, "/")
            await self._scan_delete(self._children_prefix, "/")
            await self._scan_delete(self._tombstone_prefix, "/")
            await self._scan_delete(self._directory_generation_prefix, "/")
            await self._client.delete(self._generation_key)

    async def close(self) -> None:
        if self._closed:
            return
        await self._flush_seed()
        if self._owns_client:
            await self._client.aclose()
        await super().close()
