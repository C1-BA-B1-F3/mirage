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

import type { Accessor } from '../../accessor/base.ts'
import type { PathSpec } from '../../types.ts'
import type { OpKwargs } from '../registry.ts'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type OpCoreFn = (...args: any[]) => unknown

/**
 * Structural subset of a backend's `CommandIO` the ops factory consumes.
 * The table in `commands/builtin/<b>/ops.ts` already carries every core
 * function the VFS/FUSE op wrappers forward to, so the same table feeds
 * both `makeGenericCommands` and `makeGenericOps`. Command-only fields
 * (`readStream`, `isMounted`, `find`, ...) are ignored.
 */
export interface OpsTable<A extends Accessor = Accessor> {
  readdir: (accessor: A, path: PathSpec, index?: OpKwargs['index']) => unknown
  readBytes: (accessor: A, path: PathSpec, index?: OpKwargs['index']) => Promise<Uint8Array>
  readRange?: (
    accessor: A,
    path: PathSpec,
    index: OpKwargs['index'],
    offset: number,
    size: number | null,
  ) => Promise<Uint8Array>
  stat: (accessor: A, path: PathSpec, index?: OpKwargs['index']) => unknown
  maxGlobMatches?: number
  write?: OpCoreFn
  mkdir?: OpCoreFn
  unlink?: OpCoreFn
  rmdir?: OpCoreFn
  rename?: OpCoreFn
  create?: OpCoreFn
  truncate?: OpCoreFn
  append?: OpCoreFn
  pwrite?: OpCoreFn
  setAttrs?: OpCoreFn
}

export interface MakeGenericOpsOptions {
  /**
   * Synthesize truncate from readBytes + write for a backend with no
   * native partial write (dropbox is the only one; a table carrying a
   * real `truncate` wins outright).
   */
  emulateTruncate?: boolean
  /** Forward `parents=true` to the core mkdir (disk). */
  mkdirParents?: boolean
  /** Op names to skip because the backend registers an irregular wrapper. */
  overrides?: ReadonlySet<string>
}
