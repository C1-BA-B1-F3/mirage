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
import { renderStub } from './render.ts'

const DEC = new TextDecoder()

describe('renderStub', () => {
  it('says its note and runs the command by name', () => {
    expect(DEC.decode(renderStub('ls', 'ls is built into mirage.'))).toBe(
      '#!/bin/sh\n# ls is built into mirage.\ncommand ls "$@"\n',
    )
  })

  it('quotes a name the shell would split', () => {
    expect(DEC.decode(renderStub('my tool', 'note'))).toContain(`command 'my tool' "$@"`)
  })
})
