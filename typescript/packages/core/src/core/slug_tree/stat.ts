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

import { FileStat, FileType } from '../../types.ts'
import { rstripSlash } from '../../utils/slash.ts'
import { mountRoot } from './rows.ts'
import type { ResolvedDirectory } from './types.ts'

/** Stat a folder of the tree, which exists only as its listing. */
export function directoryStat(resolved: ResolvedDirectory): FileStat {
  const key = resolved.virtualKey
  const name =
    key === mountRoot(resolved.mountPrefix) ? '/' : (rstripSlash(key).split('/').pop() ?? '/')
  return new FileStat({ name, type: FileType.DIRECTORY, extra: { children_count: 0 } })
}
