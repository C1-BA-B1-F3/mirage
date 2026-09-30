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
import { runCli } from './cli.ts'

const DEC = new TextDecoder()

describe('runCli', () => {
  it('returns both streams and the status', async () => {
    const r = await runCli(
      'sh',
      'no sh',
      ['-c', 'cat; echo e >&2; exit 3'],
      new TextEncoder().encode('in'),
    )
    expect([DEC.decode(r.stdout), DEC.decode(r.stderr), r.code]).toEqual(['in', 'e\n', 3])
  })

  it('rejects a missing CLI with its hint', async () => {
    await expect(runCli('mirage-no-such-cli', 'install it', [], null)).rejects.toThrow('install it')
  })

  it('kills the child when the call is aborted', async () => {
    const controller = new AbortController()
    const started = Date.now()
    const run = runCli('sh', 'no sh', ['-c', 'exec sleep 30'], null, controller.signal)
    setTimeout(() => {
      controller.abort()
    }, 50)
    await expect(run).rejects.toThrow()
    expect(Date.now() - started).toBeLessThan(5000)
  })
})
