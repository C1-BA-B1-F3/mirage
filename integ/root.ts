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

import { existsSync, mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import type { BaseVFS } from '@struktoai/mirage-node'
import {
  configToWorkspaceArgs,
  DiskVFS,
  loadWorkspaceConfig,
  MountMode,
  RAMVFS,
  Workspace,
} from '@struktoai/mirage-node'

const ENC = new TextEncoder()

let fail = 0

function check(label: string, cond: boolean): void {
  if (cond) {
    process.stdout.write(`OK   ${label}\n`)
  } else {
    fail += 1
    process.stdout.write(`FAIL ${label}\n`)
  }
}

async function out(ws: Workspace, cmd: string, stdin?: Uint8Array): Promise<string> {
  const res = await ws.shell(cmd, stdin === undefined ? {} : { stdin })
  return res.stdoutText
}

function rootVfs(ws: Workspace): BaseVFS | undefined {
  return ws.mounts().find((m) => m.prefix === '/')?.vfs
}

async function withTempDir(body: (dir: string) => Promise<void>): Promise<void> {
  const dir = mkdtempSync(join(tmpdir(), 'mirage-root-'))
  try {
    await body(dir)
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
}

async function defaultRootIsRam(): Promise<void> {
  const ws = new Workspace({ '/data/': new RAMVFS() }, { mode: MountMode.WRITE })
  const root = rootVfs(ws)
  check('default: root is a normal mount entry at /', root !== undefined)
  check('default: root backed by ram', root instanceof RAMVFS)
  const ls = await out(ws, 'ls /')
  check('default: ls / lists child mounts', ls.includes('data') && ls.includes('dev'))
  check('default: ls / hides dotfile mounts', !ls.includes('.bash_history'))
  await ws.shell('echo scratch > /note.txt')
  check(
    'default: write to unmounted / lands on root scratch',
    (await out(ws, 'cat /note.txt')).trim() === 'scratch',
  )
  const wc = await out(ws, 'wc -c', ENC.encode('abcd'))
  check('default: arg-less command resolves at root', wc.trim() === '4')
  await ws.close()
}

async function ramRootOverride(): Promise<void> {
  const ws = new Workspace({ '/': new RAMVFS(), '/sub/': new RAMVFS() }, { mode: MountMode.WRITE })
  check(
    'ram-root: / is the user mount (not duplicated)',
    ws.mounts().filter((m) => m.prefix === '/').length === 1,
  )
  await ws.shell('echo hi > /top.txt')
  await ws.shell('echo deep > /sub/inner.txt')
  check('ram-root: read file written at root', (await out(ws, 'cat /top.txt')).trim() === 'hi')
  const ls = await out(ws, 'ls /')
  check(
    'ram-root: ls / shows root file and child mount',
    ls.includes('top.txt') && ls.includes('sub'),
  )
  check(
    'ram-root: read through child mount',
    (await out(ws, 'cat /sub/inner.txt')).trim() === 'deep',
  )
  await ws.close()
}

async function diskRootOverride(): Promise<void> {
  await withTempDir(async (tmp) => {
    const ws = new Workspace({ '/': new DiskVFS({ root: tmp }) }, { mode: MountMode.WRITE })
    check('disk-root: root backed by disk', rootVfs(ws) instanceof DiskVFS)
    await ws.shell('echo persisted > /file.txt')
    check(
      'disk-root: read file back through root',
      (await out(ws, 'cat /file.txt')).trim() === 'persisted',
    )
    const onDisk = join(tmp, 'file.txt')
    check('disk-root: write at / persisted to the real disk path', existsSync(onDisk))
    if (existsSync(onDisk)) {
      check(
        'disk-root: on-disk content matches',
        readFileSync(onDisk, 'utf8').trim() === 'persisted',
      )
    }
    await ws.close()
  })
}

async function yamlControlsRoot(): Promise<void> {
  await withTempDir(async (tmp) => {
    const args = await configToWorkspaceArgs(
      loadWorkspaceConfig({ mounts: { '/': { vfs: 'disk', config: { root: tmp } } } }),
    )
    check("yaml: '/' mount present in mounts", '/' in args.mounts)
    const ws = new Workspace(args.mounts, args.options)
    check('yaml: root overridden to disk via config', rootVfs(ws) instanceof DiskVFS)
    await ws.shell('echo fromyaml > /y.txt')
    check('yaml: write at / persisted to disk', existsSync(join(tmp, 'y.txt')))
    await ws.close()
  })

  const args = await configToWorkspaceArgs(
    loadWorkspaceConfig({ mounts: { '/data': { vfs: 'ram' } } }),
  )
  const ws = new Workspace(args.mounts, args.options)
  check("yaml: no '/' mount falls back to ram root", rootVfs(ws) instanceof RAMVFS)
  await ws.close()
}

async function main(): Promise<void> {
  await defaultRootIsRam()
  await ramRootOverride()
  await diskRootOverride()
  await yamlControlsRoot()
  if (fail) {
    process.stdout.write(`\n${String(fail)} check(s) failed\n`)
    process.exit(1)
  }
  process.stdout.write('\nroot mount OK\n')
}

main().catch((err: unknown) => {
  process.stderr.write(String(err) + '\n')
  process.exit(1)
})
