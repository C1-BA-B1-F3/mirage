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

// Pinned against bash 5.2.37. Mirrors
// python/tests/workspace/executor/builtins/alias/test_alias.py.

import { describe, expect, it } from 'vitest'
import { RAMVFS } from '../../../../vfs/ram/ram.ts'
import { MountMode } from '../../../../types.ts'
import { getTestParser, stdoutStr } from '../../../fixtures/workspace_fixture.ts'
import { Workspace } from '../../../workspace/workspace.ts'

describe('alias', () => {
  // Pinned against bash 5.2.37: an alias is tried before a reserved word where
  // a command starts, but inside its own text, which it never expands again,
  // its name is the reserved word.
  it.each([
    ["fi='echo F'", 'fi', 'F\n', 0],
    ["fi='echo F; fi'", 'fi', '', 2],
    ["fi='echo ☕; fi'", 'fi', '', 2],
    ["c='echo C; fi ' fi='echo F'", 'c fi', 'C\nF echo F\n', 0],
    ["c='echo C; ' fi='echo F; fi'", 'c fi', '', 2],
  ])('runs alias %s as %j spelled as a reserved word', async (aliases, line, out, code) => {
    const ws = new Workspace(
      { '/data': new RAMVFS() },
      { mode: MountMode.WRITE, shellParser: await getTestParser() },
    )
    await ws.shell(`shopt -s expand_aliases; alias ${aliases}`)
    const io = await ws.shell(line)
    expect([stdoutStr(io), io.exitCode]).toEqual([out, code])
  })

  it('keeps the arguments of an alias after a non-ASCII assignment', async () => {
    const ws = new Workspace(
      { '/data': new RAMVFS() },
      { mode: MountMode.WRITE, shellParser: await getTestParser() },
    )
    await ws.shell("shopt -s expand_aliases; alias e='echo E'")
    const io = await ws.shell('X=☕ e arg')
    expect([stdoutStr(io), io.exitCode]).toEqual(['E arg\n', 0])
  })
})
