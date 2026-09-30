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

import type { BaseVFS } from './vfs/base.ts'
import { DriverOps } from './vfs/testing.ts'

const TABLES = new WeakMap<BaseVFS, DriverOps>()

/** The op table of `vfs`, bound once per instance so its index store persists across calls. */
export function ops(vfs: BaseVFS): DriverOps {
  let table = TABLES.get(vfs)
  if (table === undefined) {
    table = new DriverOps(vfs)
    TABLES.set(vfs, table)
  }
  return table
}
