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
import { CommandSpec, Operand, Option } from '../spec/types.ts'
import type { CommandOpts } from '../config.ts'
import type { CLIDoors } from './types.ts'
import { CLISpec, type CLIVerbFn } from './types.ts'

const verb: CLIVerbFn = () => null

const configModel = (input: Record<string, unknown>) => input

function tree(): CLISpec {
  return new CLISpec({
    name: 'gws',
    description: 'Google Workspace',
    configModel,
    subcommands: [
      new CLISpec({
        name: 'gmail',
        description: 'Gmail messages',
        subcommands: [
          new CLISpec({
            name: 'send',
            fn: verb,
            write: true,
            options: [
              new Option({
                short: '-t',
                long: '--to',
                type: 'str',
                multiple: true,
                required: true,
              }),
            ],
            rest: new Operand({ type: 'str' }),
          }),
          new CLISpec({ name: 'list', fn: verb }),
        ],
      }),
      new CLISpec({
        name: 'docs',
        description: 'Google Docs',
        subcommands: [new CLISpec({ name: 'cat', fn: verb })],
      }),
    ],
  })
}

describe('CLISpec', () => {
  it('builds a tree and is a CommandSpec', () => {
    const gws = tree()
    expect(gws).toBeInstanceOf(CommandSpec)
    expect(gws.subcommands.map((child) => child.name)).toEqual(['gmail', 'docs'])
    const gmail = gws.subcommands[0]
    const send = gmail?.subcommands[0]
    expect(send?.write).toBe(true)
    expect(send?.fn).toBe(verb)
    expect(send?.options[0]?.long).toBe('--to')
    expect(gws.configModel).toBe(configModel)
    expect(gmail?.configModel).toBeNull()
  })

  it('allows a single-verb leaf root', () => {
    const single = new CLISpec({ name: 'hello', fn: verb })
    expect(single.subcommands).toEqual([])
    expect(single.write).toBe(false)
    expect(single.limit).toBeNull()
  })

  it('allows group-level options', () => {
    const git = new CLISpec({
      name: 'git',
      options: [new Option({ short: '-C', type: 'path' })],
      subcommands: [new CLISpec({ name: 'status', fn: verb })],
    })
    expect(git.options[0]?.short).toBe('-C')
  })

  it('stays frozen like every spec', () => {
    const gws = tree()
    expect(Object.isFrozen(gws)).toBe(true)
    expect(Object.isFrozen(gws.subcommands)).toBe(true)
    expect(Object.isFrozen(new CommandSpec({}))).toBe(true)
  })
})

describe('doors parity with the command tier', () => {
  it('spells every door the way CommandOpts spells it', () => {
    // A CLI leaf and a command handler reach the same planes. Spelling one
    // fact two ways is how the two tiers end up with two vocabularies for one
    // plane, and then with two behaviors. Checked at compile time because a
    // TS interface has no fields to enumerate at runtime: a door CommandOpts
    // does not declare fails to index, and a door whose type drifted fails to
    // assign. The Python twin is tests/commands/cli/test_doors_parity.py.
    type Shared = { [K in keyof CLIDoors]: CommandOpts[K] }
    const parity: Shared = {} as CLIDoors
    expect(parity).toBeDefined()
  })
})
