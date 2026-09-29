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
import { jqOptions } from '../../../core/jq/index.ts'
import { materialize } from '../../../io/types.ts'
import { PathSpec } from '../../../types.ts'
import type { CommandOpts } from '../../config.ts'
import { specOf } from '../../spec/builtins.ts'
import { FlagView } from '../../spec/flag_view.ts'
import {
  exitCode,
  inputName,
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
  '/d/bad.json': '{"a":1}\n{"a":2}\n[',
  '/d/rows.jsonl': '{"a":1}\n{"a":2}\n',
  '/d/pairs.jsonl': '[1,2]\n[3]\n',
  '/d/seq.json': '\u001e1\n\u001e[1 2]\n\u001e3\n',
  '/d/one.json': '1',
  '/d/two.json': ' 2\n',
}

async function* read(path: PathSpec): AsyncIterable<Uint8Array> {
  await Promise.resolve()
  const text = FILES[path.virtual]
  if (text === undefined) throw new Error(`no such file: ${path.virtual}`)
  const bytes = ENC.encode(text)
  for (let at = 0; at < bytes.length; at += 5) yield bytes.subarray(at, at + 5)
}

interface Ran {
  readonly stdout: string
  readonly stderr: string
  readonly exitCode: number
}

/** Run jq over files and return what it printed and how it exited. */
async function ranOver(
  paths: readonly string[],
  program: string,
  flags: CommandOpts['flags'] = {},
): Promise<Ran> {
  const opts = {
    stdin: null,
    flags: { compact_output: true, ...flags },
    filetypeFns: null,
    cwd: '/',
    vfs: { kind: 'ram' } as never,
  } as CommandOpts
  const specs = paths.map((path) => PathSpec.fromStrPath(path))
  const result = await jqGeneric(specs, [program], opts, read)
  if (result === null) throw new Error('jq returned no result')
  const [out, io] = result
  return {
    stdout: DEC.decode(await materialize(out)),
    stderr: DEC.decode(await materialize(io.stderr)),
    exitCode: io.exitCode,
  }
}

/** Run jq over one file and return what it printed and how it exited. */
async function ran(path: string, program: string, flags: CommandOpts['flags'] = {}): Promise<Ran> {
  return ranOver([path], program, flags)
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
    const status = runStatus({
      outputs: [false],
      stop: { kind: 'halt', message: null, string: false, code },
    })
    expect(exitCode([status], jqOptions({ exitStatus }))).toBe(expected)
  })
})

describe('runPosition', () => {
  it('places a run where the reader stops for it', () => {
    const positions = ['f0.json:1', 'f0.json:2', 'f0.json:3']
    const end = 'f0.json:3'
    const none = { input: false, inputs: false }
    expect(runPosition(positions, end, none, 1, 0)).toBe('f0.json:2')
    expect(runPosition(positions, end, none, null, 0)).toBe('<unknown>')
    expect(runPosition(positions, end, { input: true, inputs: false }, 0, 1)).toBe('f0.json:2')
    expect(runPosition(positions, end, { input: true, inputs: false }, 2, 0)).toBe('f0.json:3')
    expect(runPosition(positions, end, { input: false, inputs: true }, 0, 2)).toBe('f0.json:3')
  })
})

describe('inputName', () => {
  it('names an input as typed, and - as stdin', () => {
    expect(
      inputName(
        new PathSpec({
          virtual: '/d/a.json',
          directory: '/d/',
          vfsPath: 'd/a.json',
          rawPath: 'a.json',
        }),
      ),
    ).toBe('a.json')
    expect(
      inputName(new PathSpec({ virtual: '/d/a.json', directory: '/d/', vfsPath: 'd/a.json' })),
    ).toBe('/d/a.json')
    expect(
      inputName(
        new PathSpec({
          virtual: '/dev/stdin',
          directory: '/dev/',
          vfsPath: 'dev/stdin',
          rawPath: '-',
        }),
      ),
    ).toBe('<stdin>')
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

  it('halts from inside a collector as from the top', async () => {
    expect(await ran('/d/four.json', 'if . == 2 then [halt_error(3)] else . end')).toEqual({
      stdout: '1\n',
      stderr: '2\n',
      exitCode: 3,
    })
  })

  it('ends the command at a halt even inside a try', async () => {
    const program = 'try (if . == 2 then halt_error(3) else . end) catch "continued"'
    expect(await ran('/d/four.json', program)).toEqual({
      stdout: '1\n',
      stderr: '2\n',
      exitCode: 3,
    })
  })

  it('refuses a program that does not compile before it reads a thing', async () => {
    const { stdout, stderr, exitCode } = await ran('/d/missing.json', '1 +')
    expect([stdout, exitCode]).toEqual(['', 3])
    expect(stderr).toMatch(/^jq: error: syntax error, .* line 1, column 3:\n {4}1 \+\n/)
    expect(stderr).toMatch(/jq: 1 compile error\n$/)
  })
})

describe('jqGeneric over malformed input', () => {
  it('ends the loop at a parse error, after the documents before it', async () => {
    expect(await ran('/d/bad.json', '.a')).toEqual({
      stdout: '1\n2\n',
      stderr: 'jq: parse error: Unfinished JSON term at EOF at line 3, column 1\n',
      exitCode: 5,
    })
  })

  it('exits five under -e too', async () => {
    const result = await ran('/d/bad.json', '.a', { exit_status: true })
    expect([result.stdout, result.exitCode]).toEqual(['1\n2\n', 5])
  })

  it('prints nothing for a slurp that meets a parse error', async () => {
    expect(await ran('/d/bad.json', '.', { slurp: true })).toEqual({
      stdout: '',
      stderr: 'jq: parse error: Unfinished JSON term at EOF at line 3, column 1\n',
      exitCode: 5,
    })
  })

  it('reports a parse error under --seq and reads on', async () => {
    expect(await ran('/d/seq.json', '.', { seq: true })).toEqual({
      stdout: '\u001e1\n\u001e3\n',
      stderr:
        'jq: ignoring parse error: Expected separator between values at line 2, ' +
        'column 6 (need RS to resync)\n',
      exitCode: 0,
    })
  })

  it('raises the parse error inside inputs as a runtime error', async () => {
    expect(await ran('/d/bad.json', '[inputs]', { null_input: true })).toEqual({
      stdout: '',
      stderr: 'jq: error (at /d/bad.json:2): Unfinished JSON term at EOF at line 3, column 1\n',
      exitCode: 5,
    })
    expect(await ran('/d/bad.json', 'try ([inputs]) catch .', { null_input: true })).toEqual({
      stdout: '"Unfinished JSON term at EOF at line 3, column 1"\n',
      stderr: '',
      exitCode: 0,
    })
  })

  it('leaves the parse error past input to the main loop', async () => {
    expect(await ran('/d/bad.json', '[., input]')).toEqual({
      stdout: '[{"a":1},{"a":2}]\n',
      stderr: 'jq: parse error: Unfinished JSON term at EOF at line 3, column 1\n',
      exitCode: 5,
    })
  })

  it('ends the command at a halt before the parse error', async () => {
    expect(await ran('/d/bad.json', '[., input] | halt_error')).toEqual({
      stdout: '',
      stderr: '[{"a":1},{"a":2}]\n',
      exitCode: 5,
    })
  })

  it('runs a value on from one input into the next', async () => {
    expect(await ranOver(['/d/one.json', '/d/two.json'], 'error(tostring)')).toEqual({
      stdout: '',
      stderr: 'jq: error (at /d/two.json:1): 1\njq: error (at /d/two.json:1): 2\n',
      exitCode: 5,
    })
  })

  it('runs the program on each line of JSON Lines unchanged', async () => {
    expect(await run('/d/rows.jsonl', '.[]')).toBe('1\n2\n')
    expect(await run('/d/pairs.jsonl', '.[] | . + 1')).toBe('2\n3\n4\n')
    expect(await ran('/d/rows.jsonl', '.[].a')).toEqual({
      stdout: '',
      stderr:
        'jq: error (at /d/rows.jsonl:1): Cannot index number with string ("a")\n' +
        'jq: error (at /d/rows.jsonl:2): Cannot index number with string ("a")\n',
      exitCode: 5,
    })
  })

  it('refuses a --slurpfile holding bad JSON in jq words', async () => {
    await expect(
      ran('/d/four.json', '$x', { null_input: true, slurpfile: ['x', '/d/bad.json'] }),
    ).rejects.toThrow(
      'jq: Bad JSON in --slurpfile x /d/bad.json: Unfinished JSON term at EOF at line 3, column 1',
    )
  })

  it("reads an --argjson value as jq's parser does", () => {
    expect(namedArgs(view({ argjson: ['v', '{"a":1}'] }))).toEqual({ v: { a: 1 } })
    expect(Number.isNaN(namedArgs(view({ argjson: ['v', 'nan'] })).v)).toBe(true)
    expect(() => namedArgs(view({ argjson: ['v', '1 2'] }))).toThrow(
      'jq: invalid JSON text passed to --argjson',
    )
  })
})
