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
import { jqOptions, type JqOptions } from '../../../core/jq/index.ts'
import { materialize } from '../../../io/types.ts'
import { PathSpec } from '../../../types.ts'
import type { CommandOpts } from '../../config.ts'
import { specOf } from '../../spec/builtins.ts'
import { FlagView } from '../../spec/flag_view.ts'
import {
  assembleInputs,
  exitCode,
  jqGeneric,
  namedArgs,
  parseFlags,
  positionalArgs,
  runPosition,
  runStatus,
} from './jq.ts'

const ENC = new TextEncoder()
const DEC = new TextDecoder()

const FILES: Record<string, string> = {
  '/d/four.json': '1\n2\n3\n4\n',
  '/d/empty.json': '',
}

async function* read(path: PathSpec): AsyncIterable<Uint8Array> {
  await Promise.resolve()
  const text = FILES[path.virtual]
  if (text === undefined) throw new Error(`no such file: ${path.virtual}`)
  yield ENC.encode(text)
}

interface Ran {
  readonly stdout: string
  readonly stderr: string
  readonly exitCode: number
}

/** Run jq over one file and return what it printed and how it exited. */
async function ran(path: string, program: string, flags: CommandOpts['flags'] = {}): Promise<Ran> {
  const opts = {
    stdin: null,
    flags: { compact_output: true, ...flags },
    filetypeFns: null,
    cwd: '/',
    vfs: { kind: 'ram' } as never,
  } as CommandOpts
  const result = await jqGeneric([PathSpec.fromStrPath(path)], [program], opts, read)
  if (result === null) throw new Error('jq returned no result')
  const [out, io] = result
  return {
    stdout: DEC.decode(await materialize(out)),
    stderr: DEC.decode(await materialize(io.stderr)),
    exitCode: io.exitCode,
  }
}

/** Run jq over one file and return what it printed. */
async function run(
  path: string,
  program: string,
  flags: CommandOpts['flags'] = {},
): Promise<string> {
  return (await ran(path, program, flags)).stdout
}

function view(flags: Record<string, string | boolean | number | string[]>): FlagView {
  return new FlagView(flags, specOf('jq'))
}

describe('parseFlags', () => {
  it('reads -j and --raw-output0 as implying -r', () => {
    expect(parseFlags(view({ join_output: true })).rawOutput).toBe(true)
    expect(parseFlags(view({ raw_output0: true })).rawOutput).toBe(true)
  })

  it('reads --indent -1 as tab indentation', () => {
    const opts = parseFlags(view({ indent: '-1' }))
    expect(opts.tab).toBe(true)
    expect(opts.indent).toBe(2)
  })

  it('refuses an indent out of range', () => {
    expect(() => parseFlags(view({ indent: '8' }))).toThrow(/between -1 and 7/)
  })
})

describe('namedArgs', () => {
  it('pairs up the flattened tokens', () => {
    expect(namedArgs(view({ arg: ['a', '1', 'b', '2'] }))).toEqual({ a: '1', b: '2' })
  })

  it('parses an --argjson value as JSON', () => {
    expect(namedArgs(view({ argjson: ['v', '{"k":[1,2]}'] }))).toEqual({ v: { k: [1, 2] } })
  })

  it('refuses invalid JSON', () => {
    expect(() => namedArgs(view({ argjson: ['v', 'nope'] }))).toThrow(/invalid JSON text/)
  })
})

/** Inputs named the way jq names files, one per text. */
function sources(...texts: string[]): [string, Uint8Array][] {
  return texts.map((text, i) => [`f${String(i)}.json`, ENC.encode(text)])
}

async function docsOf(opts: JqOptions, ...texts: string[]): Promise<unknown[]> {
  const [docs] = await assembleInputs(sources(...texts), opts)
  return docs
}

describe('assembleInputs', () => {
  it('slurps across every input rather than each one', async () => {
    expect(await docsOf(jqOptions({ slurp: true }), '{"a":1}', '{"b":2}')).toEqual([
      [{ a: 1 }, { b: 2 }],
    ])
  })

  it('splits raw lines per input', async () => {
    expect(await docsOf(jqOptions({ rawInput: true }), 'x\ny', 'z\n')).toEqual(['x', 'y', 'z'])
  })

  it('joins every input into one string when raw and slurped', async () => {
    const opts = jqOptions({ rawInput: true, slurp: true })
    expect(await docsOf(opts, 'x\n', 'y\n')).toEqual(['x\ny\n'])
  })

  it('places each document where jq reads it whole', async () => {
    const [, positions] = await assembleInputs(sources('1\n2\n', '[3,\n4]\n5'), jqOptions())
    expect([0, 1, 2, 3].map((doc) => positions.at(doc))).toEqual([
      'f0.json:1',
      'f0.json:2',
      'f1.json:2',
      'f1.json:2',
    ])
    expect(positions.end()).toBe('f1.json:2')
  })

  it('places a slurp at the end of the last input', async () => {
    const [, positions] = await assembleInputs(sources('1\n', '2\n3'), jqOptions({ slurp: true }))
    expect(positions.at(0)).toBe('f1.json:1')
  })
})

describe('exitCode', () => {
  const printed = (...outputs: unknown[]): number => runStatus({ outputs, stop: null })
  const failed = runStatus({ outputs: [1], stop: { kind: 'error', text: 'x', string: true } })

  it('reads the last output only under -e', () => {
    const opts = jqOptions({ exitStatus: true })
    expect(exitCode([printed(1, false)], opts)).toBe(1)
    expect(exitCode([printed(false, 1)], opts)).toBe(0)
    expect(exitCode([printed(null)], opts)).toBe(1)
    expect(exitCode([], opts)).toBe(4)
  })

  it('is zero without the flag', () => {
    expect(exitCode([], jqOptions())).toBe(0)
    expect(exitCode([printed(null)], jqOptions())).toBe(0)
  })

  it('counts a failed run only when it is the last one', () => {
    expect(exitCode([failed, printed(1)], jqOptions())).toBe(0)
    expect(exitCode([printed(1), failed], jqOptions())).toBe(5)
    expect(exitCode([failed, printed(false)], jqOptions({ exitStatus: true }))).toBe(1)
  })

  it('looks back past runs that printed nothing under -e', () => {
    const opts = jqOptions({ exitStatus: true })
    expect(exitCode([printed(false), printed()], opts)).toBe(1)
    expect(exitCode([printed(1), printed()], opts)).toBe(0)
  })

  it.each([
    [null, false, 0],
    [2, false, 2],
    [-1, false, 0],
    [-1, true, 1],
    [1.5, false, 1],
    [300, false, 44],
  ])('exits a halt with code %s (-e %s) as %s', (code, exitStatus, expected) => {
    const status = runStatus({ outputs: [false], stop: { kind: 'halt', text: '', code } })
    expect(exitCode([status], jqOptions({ exitStatus }))).toBe(expected)
  })
})

describe('runPosition', () => {
  it('places a run where the reader stops for it', async () => {
    const [, positions] = await assembleInputs(sources('1\n2\n3\n'), jqOptions())
    const none = { input: false, inputs: false }
    expect(runPosition(positions, none, 1, 0)).toBe('f0.json:2')
    expect(runPosition(positions, none, null, 0)).toBe('<unknown>')
    expect(runPosition(positions, { input: true, inputs: false }, 0, 1)).toBe('f0.json:2')
    expect(runPosition(positions, { input: true, inputs: false }, 2, 0)).toBe('f0.json:3')
    expect(runPosition(positions, { input: false, inputs: true }, 0, 2)).toBe('f0.json:3')
  })
})

describe('positionalArgs', () => {
  it('reads the operands after the program as text', () => {
    expect(positionalArgs(view({ args: true }), ['.', 'a', 'b'], false)).toEqual(['a', 'b'])
  })

  it('keeps every operand when -f gave the program', () => {
    expect(positionalArgs(view({ args: true }), ['a', 'b'], true)).toEqual(['a', 'b'])
  })

  it('parses each operand under --jsonargs', () => {
    expect(positionalArgs(view({ jsonargs: true }), ['.', '1', '{"k":2}'], false)).toEqual([
      1,
      { k: 2 },
    ])
  })

  it('refuses invalid JSON under --jsonargs', () => {
    expect(() => positionalArgs(view({ jsonargs: true }), ['.', 'nope'], false)).toThrow(
      /invalid JSON text/,
    )
  })

  it('is empty without either flag', () => {
    expect(positionalArgs(view({}), ['.', 'a'], false)).toEqual([])
  })
})

describe('assembleInputs with --stream and --seq', () => {
  it('expands documents into events', async () => {
    expect(await docsOf(jqOptions({ stream: true }), '{"a":1}')).toEqual([[['a'], 1], [['a']]])
  })

  it('collects the events when slurped', async () => {
    expect(await docsOf(jqOptions({ stream: true, slurp: true }), '{"a":1}')).toEqual([
      [[['a'], 1], [['a']]],
    ])
  })

  it('reads only RS-introduced values', async () => {
    expect(await docsOf(jqOptions({ seq: true }), '\u001e{"a":1}\n\u001e{"a":2}\n')).toEqual([
      { a: 1 },
      { a: 2 },
    ])
  })

  it('drops text before the first separator', async () => {
    expect(await docsOf(jqOptions({ seq: true }), '{"a":1}\n')).toEqual([])
  })
})

describe('jqGeneric over a stream that input and inputs read', () => {
  it('gives -n input the first document', async () => {
    expect(await run('/d/four.json', 'input', { null_input: true })).toBe('1\n')
  })

  it('leaves inputs what input did not take', async () => {
    expect(await run('/d/four.json', 'input as $h | [inputs]', { null_input: true })).toBe(
      '[2,3,4]\n',
    )
    expect(await run('/d/four.json', '[input, inputs]', { null_input: true })).toBe('[1,2,3,4]\n')
  })

  it('takes one document per run for input alone', async () => {
    expect(await run('/d/four.json', '[., input]')).toBe('[1,2]\n[3,4]\n')
    expect(await run('/d/four.json', 'input')).toBe('2\n4\n')
  })

  it('drains the rest of the stream in one run for inputs', async () => {
    expect(await run('/d/four.json', '[., inputs]')).toBe('[1,2,3,4]\n')
  })

  it('fails input with break when the stream is empty', async () => {
    expect(await ran('/d/empty.json', 'input', { null_input: true })).toEqual({
      stdout: '',
      stderr: 'jq: error (at /d/empty.json:0): break\n',
      exitCode: 5,
    })
  })

  it('still runs a program that reads no stream once per document', async () => {
    expect(await run('/d/four.json', '. * 10')).toBe('10\n20\n30\n40\n')
  })
})

describe('jqGeneric runs that stop early', () => {
  it('prints what came before an error, reports it, and goes on', async () => {
    expect(await ran('/d/four.json', 'if . == 2 then error("two") else . end')).toEqual({
      stdout: '1\n3\n4\n',
      stderr: 'jq: error (at /d/four.json:2): two\n',
      exitCode: 0,
    })
    expect(await ran('/d/four.json', '., error({n: .}) | select(. > 3)')).toMatchObject({
      stdout: '4\n',
      exitCode: 5,
    })
  })

  it('says when the message was not a string', async () => {
    const { stderr } = await ran('/d/four.json', 'if . == 4 then error({n: .}) else empty end')
    expect(stderr).toBe('jq: error (at /d/four.json:4) (not a string): {"n":4}\n')
  })

  it('ends the whole invocation at a halt', async () => {
    expect(await ran('/d/four.json', 'if . == 2 then "bye\\n" | halt_error(3) else . end')).toEqual(
      {
        stdout: '1\n',
        stderr: 'bye\n',
        exitCode: 3,
      },
    )
    expect(await ran('/d/four.json', 'if . == 3 then halt else . end')).toEqual({
      stdout: '1\n2\n',
      stderr: '',
      exitCode: 0,
    })
  })

  it('refuses a program that does not compile before it reads a thing', async () => {
    const { stdout, stderr, exitCode } = await ran('/d/missing.json', '1 +')
    expect([stdout, exitCode]).toEqual(['', 3])
    expect(stderr).toMatch(/^jq: error: syntax error, .* line 1, column 3:\n {4}1 \+\n/)
    expect(stderr).toMatch(/jq: 1 compile error\n$/)
  })
})
