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

import type { IndexEntry } from '../../cache/index/config.ts'

/** Each folder's `[name, entry]` rows, keyed by the folder's virtual key. */
export type DirRows = Map<string, [string, IndexEntry][]>

/** Fetch a backend's whole document list and lay it out under a mount prefix. */
export type LoadRows<A> = (accessor: A, prefix: string) => Promise<DirRows>

export interface ResolvedDirectory {
  readonly isDir: true
  readonly virtualKey: string
  readonly mountPrefix: string
  readonly children: string[] | undefined
}

export interface ResolvedFile {
  readonly isDir: false
  readonly virtualKey: string
  readonly mountPrefix: string
  readonly entry: IndexEntry
}

export type ResolvedPath = ResolvedDirectory | ResolvedFile

export interface WalkOptions {
  includeRoot?: boolean
  maxDepth?: number | null
  stripPrefix?: boolean
  ignoreMissing?: boolean
  depth?: number
}
