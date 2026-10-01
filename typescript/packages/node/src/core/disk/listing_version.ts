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

import type { BigIntStats } from 'node:fs'
import { stat as fsStat } from 'node:fs/promises'
import { RACY_WINDOW_NS } from './constants.ts'

/** The wall clock a folder version is judged against, in nanoseconds. */
export function wallNs(): bigint {
  return BigInt(Date.now()) * 1000000n
}

/**
 * The listing version of a folder, from its stat.
 *
 * A disk listing holds only names and types, and every add, rename or remove
 * inside a folder moves that folder's change time, so the folder's own stat
 * covers its listing. The inode and device catch a folder made again or a
 * filesystem mounted over it; the mtime covers a platform whose ctime is a
 * creation time. A folder changed less than `RACY_WINDOW_NS` before `nowNs`
 * gets no version, since a second change within one timestamp tick would
 * leave it unmoved.
 *
 * @param st - the folder's bigint stat, links followed.
 * @param nowNs - the wall clock, read before the stat.
 * @returns `dev:ino:ctimeNs:mtimeNs`, or null while the folder is settling.
 */
export function stamp(st: BigIntStats, nowNs: bigint): string | null {
  const changed = st.ctimeNs > st.mtimeNs ? st.ctimeNs : st.mtimeNs
  if (nowNs - changed < RACY_WINDOW_NS) return null
  return `${String(st.dev)}:${String(st.ino)}:${String(st.ctimeNs)}:${String(st.mtimeNs)}`
}

/**
 * Stat a host folder and return its listing version.
 *
 * @param path - the host folder, already checked by `resolveInside`.
 * @param nowNs - the wall clock, read before this call.
 */
export async function folderVersion(path: string, nowNs: bigint): Promise<string | null> {
  return stamp(await fsStat(path, { bigint: true }), nowNs)
}
