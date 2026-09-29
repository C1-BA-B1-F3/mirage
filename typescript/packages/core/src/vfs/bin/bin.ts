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

import { BinAccessor } from '../../accessor/bin.ts'
import { BIN_COMMANDS } from '../../commands/builtin/bin/index.ts'
import type { RegisteredCommand } from '../../commands/config.ts'
import { BIN_OPS } from '../../ops/bin/index.ts'
import type { RegisteredOp } from '../../ops/registry.ts'
import { VFSName } from '../../types.ts'
import { BaseVFS } from '../base.ts'

/**
 * Read-only view VFS backing the /usr/bin mount. Lists one executable
 * file per program the session can run, rendered from the workspace's
 * command lookup on every call; holds no storage of its own.
 */
export class BinViewVFS extends BaseVFS {
  override readonly name = VFSName.BIN
  override readonly cachesReads = false
  // A stub's size is its rendering: cheap, no network, never null.
  override readonly sizesAlwaysKnown = true
  override readonly accessor: BinAccessor

  constructor(programs: () => string[], note: (name: string) => string | null) {
    super()
    this.accessor = new BinAccessor(programs, note)
  }

  override ops(): readonly RegisteredOp[] {
    return BIN_OPS
  }

  override commands(): readonly RegisteredCommand[] {
    return BIN_COMMANDS
  }
}
