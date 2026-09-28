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
import { failureText } from './failure.ts'

describe('failureText', () => {
  it("prints an Error's message", () => {
    expect(failureText(new RangeError('boom'))).toBe('boom')
  })

  it('names a plain object instead of printing [object Object]', () => {
    const exit = { name: 'ExitStatus', message: 'Program terminated with exit(1)', status: 1 }
    expect(failureText(exit)).toBe('ExitStatus: Program terminated with exit(1)')
    expect(failureText({ message: 'no name' })).toBe('no name')
  })

  it('lists the keys of an object with neither a name nor a message', () => {
    expect(failureText({ status: 7, signal: 'SIGKILL' })).toBe(
      'an object with keys: status, signal',
    )
    expect(failureText({})).toBe('an object with keys: (none)')
  })

  it('prints a primitive as it is', () => {
    expect(failureText('unwind')).toBe('unwind')
    expect(failureText(null)).toBe('null')
  })
})
