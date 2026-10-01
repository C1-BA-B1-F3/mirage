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

import { FD_BOTH, FD_CLOSE } from './constants.ts'
import { SharedInput } from '../io/async_line_iterator.ts'
import type { PathSpec } from '../types.ts'
import { ebadfStdin } from '../utils/errors.ts'
import { RedirectKind, type Redirect } from './types.ts'

/**
 * The first descriptor outside the signed 32-bit range, or null. Both slots count: the
 * descriptor a redirect claims (`3>f`, `3<f`, `3>&1`, `3>&-`) and the one
 * it duplicates from (`>&3`, `<&3`, `2>&3`). `&>`'s FD_BOTH and `>&-`'s
 * FD_CLOSE are the two sentinels the parser spells with -1, and neither is
 * a descriptor.
 */
export function unsupportedDescriptor(redirects: readonly Redirect[]): number | null {
  for (const r of redirects) {
    // An ambiguous redirect (`3>&word`) is skipped: bash refuses it in its
    // own words before it judges the descriptor, and so does the installer.
    if (r.kind === RedirectKind.AMBIGUOUS) continue
    if (!(r.fd >= 0 && r.fd < 2 ** 31) && r.fd !== FD_BOTH) return r.fd
    if (
      typeof r.target === 'number' &&
      !(r.target >= 0 && r.target < 2 ** 31) &&
      r.target !== FD_CLOSE
    ) {
      return r.target
    }
  }
  return null
}

/** Bash's error for a closed descriptor, without the line-number prefix. */
export function badDescriptorLine(fd: number): Uint8Array {
  return new TextEncoder().encode(`${String(fd)}: Bad file descriptor\n`)
}

/**
 * Standard input that fails on its first read with EBADF. bash opens a
 * command whose stdin is closed (`<&-`) or duplicated from a write-only
 * descriptor (`0<&1`) all the same; the descriptor exists, and only a
 * read of it fails. A command that never reads (`true 0<&1`) succeeds,
 * and one that does reports `<cmd>: -: Bad file descriptor` and exits 1,
 * which is what the chokepoint renders from the error this throws.
 */
export function unreadableStdin(): AsyncIterable<Uint8Array> {
  return {
    [Symbol.asyncIterator]: () => ({ next: () => Promise.reject(ebadfStdin()) }),
  }
}

export class FileDescription {
  opened = false
  offset = 0
  source: FileInput | null = null
  emit: ((data: Uint8Array) => Promise<void>) | null = null
  constructor(
    readonly scope: PathSpec,
    readonly append = false,
  ) {}
}

export class FileInput extends SharedInput {
  constructor(
    readonly description: FileDescription,
    data: Uint8Array,
  ) {
    super(data)
  }
  override dup(): this {
    return this
  }
}

export interface Descriptor {
  readonly identity: string
  readonly append: boolean
  readonly source: SharedInput | null
  readonly file: FileDescription | null
}
