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

// Pinned against GNU bash 5.2.37: `[` is a command, so every operator the
// grammar folds into a `[ ... ]` test reaches it as an operand word, and test
// refuses the ones it does not know rather than never seeing them. Mirrors
// python/tests/workspace/node/test_test_expr.py.

import { describe, expect, it } from 'vitest'
import { RAMVFS } from '../../vfs/ram/ram.ts'
import { MountMode } from '../../types.ts'
import { getTestParser, stderrStr, stdoutStr } from '../fixtures/workspace_fixture.ts'
import { Workspace } from '../workspace/workspace.ts'

describe('expandTestExpr', () => {
  it.each([
    ['[ a == a ] && echo y', 'y\n', ''],
    ['[ $ ] && echo y', 'y\n', ''],
    ['[ a =~ a ]; echo $?', '2\n', 'bash: [: =~: binary operator expected\n'],
    ['[ 1 + 1 ]; echo $?', '2\n', 'bash: [: +: binary operator expected\n'],
    ['[ a += b ]; echo $?', '2\n', 'bash: [: +=: binary operator expected\n'],
    ['[ a -= b ]; echo $?', '2\n', 'bash: [: -=: binary operator expected\n'],
  ])('hands every operator in %j to test as a word', async (line, out, err) => {
    const ws = new Workspace(
      { '/data': new RAMVFS() },
      { mode: MountMode.WRITE, shellParser: await getTestParser() },
    )
    const io = await ws.shell(line)
    expect([stdoutStr(io), stderrStr(io)]).toEqual([out, err])
  })
})
