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

import { describe, expect, it } from 'vitest'
import type { S3BrowserPresignedUrlProvider } from './config.ts'
import { S3VFS } from './s3.ts'

const provider: S3BrowserPresignedUrlProvider = () => Promise.resolve('https://signed.example.com')

// Keys are `prefix + path`, so the prefix is normalized on construction as
// node's S3VFS does; the browser kept it raw, and `team/x` keyed
// `team/xa.txt`. A root-spelled prefix is no prefix.
const PREFIX_SPELLINGS: readonly [string | undefined, string | undefined][] = [
  ['/team/x/', 'team/x/'],
  ['team/x', 'team/x/'],
  ['', undefined],
  [undefined, undefined],
  ['/', undefined],
]

describe('S3VFS keyPrefix', () => {
  it.each(PREFIX_SPELLINGS)('%j is kept as %j', (raw, expected) => {
    const vfs = new S3VFS({
      bucket: 'b',
      presignedUrlProvider: provider,
      ...(raw === undefined ? {} : { keyPrefix: raw }),
    })
    expect(vfs.config.keyPrefix).toBe(expected)
    expect(vfs.accessor.config.keyPrefix).toBe(expected)
  })
})
