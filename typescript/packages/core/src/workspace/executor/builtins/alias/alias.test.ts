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
  it('runs an alias spelled as a reserved word', async () => {
    // bash tries an alias before a reserved word where a command starts, so
    // with expand_aliases on, an alias named `fi` is a command.
    const ws = new Workspace(
      { '/data': new RAMVFS() },
      { mode: MountMode.WRITE, shellParser: await getTestParser() },
    )
    await ws.shell("shopt -s expand_aliases; alias fi='echo F'")
    const io = await ws.shell('fi')
    expect([stdoutStr(io), io.exitCode]).toEqual(['F\n', 0])
  })
})
