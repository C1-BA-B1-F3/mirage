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

import type { BinAccessor } from '../../accessor/bin.ts'
import { BIN_IO } from '../../commands/builtin/bin/io.ts'
import { refuse } from '../../core/bin/refuse.ts'
import { VFSName } from '../../types.ts'
import { makeGenericOps } from '../generic/factory.ts'
import type { RegisteredOp } from '../registry.ts'

// The IO wires reads only, so the view registers no write command; each
// write op is its own refusal instead of a missing op, which would answer
// "Operation not supported" where a read-only directory says EROFS.
export const BIN_OPS: readonly RegisteredOp[] = [
  ...makeGenericOps(VFSName.BIN, BIN_IO),
  ...['write', 'append', 'create', 'mkdir', 'unlink', 'rmdir', 'rename', 'truncate', 'setattr'].map(
    (name): RegisteredOp => ({
      name,
      vfs: VFSName.BIN,
      filetype: null,
      fn: (accessor, path) => refuse(accessor as BinAccessor, path),
      write: true,
    }),
  ),
]
