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

import { cliSpecFor } from '../../../commands/cli/specs.ts'
import { DeviceInput } from '../../../io/types.ts'
import { OpsRegistry } from '../../../ops/registry.ts'
import { RAMVFS } from '../../../vfs/ram/ram.ts'
import { MountMode, PathSpec } from '../../../types.ts'
import { Workspace } from '../../workspace/workspace.ts'
import { defaultCwdOperand, pathFlagScopes, programTokens } from './routing.ts'

describe('pathFlagScopes', () => {
  it.each([
    ['grep', '-f'],
    ['rg', '-f'],
    ['zgrep', '-f'],
    ['sed', '-f'],
    ['awk', '-f'],
    ['jq', '--from-file'],
  ])('leaves %s %s program file out', (cmd, flag) => {
    // The program file is read before routing, so a pattern file on
    // another mount does not make the line cross-mount, for every command
    // that reads one: the keys come from the reader's own table.
    expect(pathFlagScopes(cmd, [flag, '/other/p', '/data/in'], '/')).toEqual([])
  })

  it.each([
    ['curl', ['-o', '/other/body', '-D', '/data/h', 'http://x.test/']],
    ['curl', ['--dump-header', '-', '--output', '/other/body', 'http://x.test/']],
    ['jq', ['--slurpfile', 's', '/other/s.json', '--rawfile', 'r', '/dev/fd/63', '.']],
  ])('leaves the files %s reads or writes through the door out', (cmd, argv) => {
    // The handler reaches them through the dispatcher, so they name no
    // mount the line has to run on (DOOR_FLAG_KEYS).
    expect(pathFlagScopes(cmd, argv, '/')).toEqual([])
  })
})

describe('programTokens', () => {
  it('walks a CLI verb path and keeps the rest raw', async () => {
    const ram = new RAMVFS()
    const ops = new OpsRegistry()
    ops.registerVfs(ram)
    const ws = new Workspace({ '/ram': ram }, { mode: MountMode.WRITE, ops })
    try {
      ws.registerCli('git', cliSpecFor('git'))
      const reg = ws.registry
      // Options before the verb are not the verb; an alias reads as its
      // canonical name; the leaf's own words follow untouched.
      expect(programTokens(reg, 'git', ['-C', '/r', 'reset', '--hard', 'HEAD'], '/')).toEqual([
        ['git', 'reset', '--hard', 'HEAD'],
        ['git', 'reset'],
      ])
      expect(programTokens(reg, 'git', ['log', '-1'], '/')).toEqual([
        ['git', 'log', '-1'],
        ['git', 'log'],
      ])
      // A walk the tree refuses (unknown verb, bare head) reads raw.
      expect(programTokens(reg, 'git', ['frobnicate', 'x'], '/')).toEqual([
        ['git', 'frobnicate', 'x'],
        ['git'],
      ])
      expect(programTokens(reg, 'git', [], '/')).toEqual([['git'], ['git']])
      // Anything else is the name and the raw argv.
      expect(programTokens(reg, 'rm', ['-rf', '/x'], '/')).toEqual([['rm', '-rf', '/x'], ['rm']])
    } finally {
      await ws.close()
    }
  })
})

describe('defaultCwdOperand', () => {
  it('searches the cwd once rg -f - takes stdin', async () => {
    // ripgrep 14.1.1: an attached stdin wins over the cwd, but `-f -` reads
    // it for patterns first, which leaves only the cwd to search. The `-`
    // arrives classified, so its spelling is what says stdin.
    const ws = new Workspace({ '/ram': new RAMVFS() }, { mode: MountMode.WRITE })
    try {
      const reg = ws.registry
      const stdin = new TextEncoder().encode('a\n')
      const dash = new PathSpec({
        virtual: '/ram/-',
        directory: '/ram/',
        vfsPath: '',
        resolved: true,
        rawPath: '-',
      })
      expect(defaultCwdOperand(['rg', '-f', dash], 'rg', reg, '/ram', stdin)?.rawPath).toBe('')
      const file = new PathSpec({ virtual: '/ram/p', directory: '/ram/', vfsPath: '' })
      expect(defaultCwdOperand(['rg', '-f', file], 'rg', reg, '/ram', stdin)).toBeNull()
      expect(defaultCwdOperand(['rg', 'a'], 'rg', reg, '/ram', stdin)).toBeNull()
    } finally {
      await ws.close()
    }
  })

  it('searches the cwd when rg stdin is a device', async () => {
    // ripgrep 14.1.1 searches stdin only when a file, FIFO or socket is
    // attached (grep_cli::is_readable_stdin): `rg a < /dev/null` searches the
    // cwd, while an empty file or pipe is still searched.
    const ws = new Workspace({ '/ram': new RAMVFS() }, { mode: MountMode.WRITE })
    try {
      const reg = ws.registry
      const device = new DeviceInput(0)
      expect(defaultCwdOperand(['rg', 'a'], 'rg', reg, '/ram', device)?.rawPath).toBe('')
      expect(defaultCwdOperand(['rg', 'a'], 'rg', reg, '/ram', new Uint8Array(0))).toBeNull()
    } finally {
      await ws.close()
    }
  })
})
