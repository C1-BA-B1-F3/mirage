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

import { expect, it } from 'vitest'
import { commandStarted, runInCommandScope } from '../../../cache/index/scope.ts'
import { IOResult } from '../../../io/types.ts'
import type { DispatchFn } from '../../../runtime/types.ts'
import { runDispatch } from './dispatch.ts'

it('reads the output inside the running command', async () => {
  // A fresh mount trusts only the listings the running command made, so a
  // walk read lazily after the command ended was served stale ones.
  const seen: (number | null)[] = []
  async function* walk(): AsyncIterable<Uint8Array> {
    await Promise.resolve()
    seen.push(commandStarted())
    yield new TextEncoder().encode('hit\n')
  }
  const dispatch = (() => Promise.reject(new Error('no op'))) as unknown as DispatchFn
  const [started, stdout] = await runInCommandScope(async () => [
    commandStarted(),
    (
      await runDispatch(
        { name: 'grep', fn: () => [walk(), new IOResult()] },
        [],
        [],
        {},
        dispatch,
        '/',
      )
    )[0],
  ])
  expect([new TextDecoder().decode(stdout as Uint8Array), seen]).toEqual(['hit\n', [started]])
})
