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

import assert from 'node:assert/strict'
import { buildVfs, MountMode, RAMVFS, registerVfsFactory, Workspace } from '@struktoai/mirage-node'

class PortableRAM extends RAMVFS {}

async function check(ws: Workspace, command: string, stdout = ''): Promise<void> {
  const result = await ws.shell(command)
  assert.equal(result.exitCode, 0, `${command}: ${result.stderrText}`)
  assert.equal(result.stderrText, '', command)
  assert.equal(result.stdoutText, stdout, command)
}

async function write(path: string): Promise<void> {
  const ws = new Workspace(
    {
      '/direct/': new RAMVFS(),
      '/nested/registered/': await buildVfs('portable-ram'),
    },
    { mode: MountMode.WRITE },
  )
  try {
    await check(ws, "printf 'portable\\n' > /direct/note.txt")
    await check(ws, "printf 'registered\\n' > /nested/registered/note.txt")
    await check(ws, 'ln -s /direct/note.txt /nested/registered/link')
    await ws.snapshot(path)
  } finally {
    await ws.close()
  }
}

async function read(path: string): Promise<void> {
  const ws = await Workspace.load(path)
  try {
    await check(ws, 'cat /direct/note.txt', 'portable\n')
    await check(ws, 'cat /nested/registered/*.txt', 'registered\n')
    await check(ws, 'cat /nested/registered/link', 'portable\n')
    assert(ws.mounts().find((m) => m.prefix === '/nested/registered/')?.vfs instanceof PortableRAM)
  } finally {
    await ws.close()
  }
}

registerVfsFactory('portable-ram', () => Promise.resolve(new PortableRAM()))
const [role, path] = process.argv.slice(2)
assert(path !== undefined, 'snapshot path is required')
if (role === 'write') await write(path)
else if (role === 'read') await read(path)
else throw new Error(`unknown role: ${String(role)}`)
