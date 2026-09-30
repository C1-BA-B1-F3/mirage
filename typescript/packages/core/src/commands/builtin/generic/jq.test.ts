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
import { materialize, type ByteSource, type IOResult } from '../../../io/types.ts'
import { PathSpec } from '../../../types.ts'
import { eisdir, enoent } from '../../../utils/errors.ts'
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
  '/d/seq_mid.json': '\u001e1\n\u001e2\n\u001e[1 2]\n\u001e3\n\u001e4\n',
  '/d/mid.json': '1\n[1 2]\n3\n4\n',
  '/d/one.json': '1',
  '/d/two.json': ' 2\n',
}

async function* read(path: PathSpec): AsyncIterable<Uint8Array> {
  await Promise.resolve()
  if (path.virtual === '/d/dir') throw eisdir(path)
  const text = FILES[path.virtual]
  if (text === undefined) throw enoent(path)
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
    expect(namedArgs(view({ arg: ['a', '1', 'b', 'x"y'] }))).toEqual(
      new Map([
        ['a', '"1"'],
        ['b', '"x\\"y"'],
      ]),
    )
  })

  it('keeps an --argjson value as the text jq reads', () => {
    expect(namedArgs(view({ argjson: ['v', ' {"b":1.000,"1":2} '] }))).toEqual(
      new Map([['v', '{"b":1.000,"1":2}']]),
    )
  })

  it('refuses invalid JSON', () => {
    expect(() => namedArgs(view({ argjson: ['v', 'nope'] }))).toThrow(/invalid JSON text/)
  })
})

/** Inputs named the way jq names files, one per text. */
describe('exitCode', () => {
  const printed = (...outputs: string[]): number => runStatus({ outputs, stop: null })
  const failed = runStatus({ outputs: ['1'], stop: { kind: 'error', text: 'x', string: true } })

  it('reads the last output only under -e', () => {
    const opts = jqOptions({ exitStatus: true })
    expect(exitCode([printed('1', 'false')], opts)).toBe(1)
    expect(exitCode([printed('false', '1')], opts)).toBe(0)
    expect(exitCode([printed('null')], opts)).toBe(1)
    expect(exitCode([printed('"false"'), printed('0.0')], opts)).toBe(0)
    expect(exitCode([], opts)).toBe(4)
  })

  it('is zero without the flag', () => {
    expect(exitCode([], jqOptions())).toBe(0)
    expect(exitCode([printed('null')], jqOptions())).toBe(0)
  })

  it('counts a failed run only when it is the last one', () => {
    expect(exitCode([failed, printed('1')], jqOptions())).toBe(0)
    expect(exitCode([printed('1'), failed], jqOptions())).toBe(5)
    expect(exitCode([failed, printed('false')], jqOptions({ exitStatus: true }))).toBe(1)
  })

  it('looks back past runs that printed nothing under -e', () => {
    const opts = jqOptions({ exitStatus: true })
    expect(exitCode([printed('false'), printed()], opts)).toBe(1)
    expect(exitCode([printed('1'), printed()], opts)).toBe(0)
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
      outputs: ['false'],
      stop: { kind: 'halt', message: null, string: false, code },
    })
    expect(exitCode([status], jqOptions({ exitStatus }))).toBe(expected)
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
  it('reads the operands after the program as strings', () => {
    expect(positionalArgs(view({ args: true }), ['.', 'a', '1'], false)).toEqual(['"a"', '"1"'])
  })

  it('keeps every operand when -f gave the program', () => {
    expect(positionalArgs(view({ args: true }), ['a', 'b'], true)).toEqual(['"a"', '"b"'])
  })

  it('keeps each operand under --jsonargs as the text jq reads', () => {
    expect(positionalArgs(view({ jsonargs: true }), ['.', '1.0', '{"b":1,"1":2}'], false)).toEqual([
      '1.0',
      '{"b":1,"1":2}',
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

  it.each(['[., input]', '[., inputs]'])(
    'fails the run that reads a parse error, and reads on past it (%s)',
    async (program) => {
      expect(await ran('/d/mid.json', program)).toEqual({
        stdout: '[3,4]\n',
        stderr:
          'jq: error (at /d/mid.json:2): Expected separator between values at line 2, column 5\n',
        exitCode: 0,
      })
    },
  )

  it('reads past a parse error under --seq, whether a run or the loop meets it', async () => {
    expect(await ran('/d/seq.json', '[., inputs]', { seq: true })).toEqual({
      stdout: '\u001e[3]\n',
      stderr:
        'jq: error (at /d/seq.json:2): Expected separator between values at line 2, ' +
        'column 6 (need RS to resync)\n',
      exitCode: 0,
    })
    expect(await ran('/d/seq_mid.json', '[., input]', { seq: true })).toEqual({
      stdout: '\u001e[1,2]\n\u001e[3,4]\n',
      stderr:
        'jq: ignoring parse error: Expected separator between values at line 3, ' +
        'column 6 (need RS to resync)\n',
      exitCode: 0,
    })
  })

  it('places a run where its reads leave the reader', async () => {
    // A run reports where the reader stands once it has read its own
    // document and whatever `input` or `inputs` took past it.
    expect(await ran('/d/four.json', '[., input] | error(tojson)')).toEqual({
      stdout: '',
      stderr: 'jq: error (at /d/four.json:2): [1,2]\njq: error (at /d/four.json:4): [3,4]\n',
      exitCode: 5,
    })
    expect(await ran('/d/four.json', '[., inputs] | error(tojson)')).toEqual({
      stdout: '',
      stderr: 'jq: error (at /d/four.json:4): [1,2,3,4]\n',
      exitCode: 5,
    })
  })

  it('reads no further than what input takes', async () => {
    // An input that holds `text` and never ends, like a producer that stays
    // open.
    async function* live(text: string): AsyncIterable<Uint8Array> {
      yield ENC.encode(text)
      await new Promise<never>(() => undefined)
    }
    async function started(
      program: string,
      text: string,
      flags: CommandOpts['flags'],
    ): Promise<[ByteSource | null, IOResult]> {
      const opts = {
        stdin: null,
        flags,
        filetypeFns: null,
        cwd: '/',
        vfs: { kind: 'ram' } as never,
      } as CommandOpts
      const result = await jqGeneric([PathSpec.fromStrPath('/d/live.json')], [program], opts, () =>
        live(text),
      )
      if (result === null) throw new Error('jq returned no result')
      return result
    }
    function soon<T>(promise: Promise<T>): Promise<T | 'still waiting'> {
      return Promise.race([
        promise,
        new Promise<'still waiting'>((resolve) => {
          setTimeout(() => {
            resolve('still waiting')
          }, 5000).unref()
        }),
      ])
    }
    const [lone, io] = await started('input', '[1 2]\n', { null_input: true })
    expect(await soon(materialize(lone))).toEqual(new Uint8Array(0))
    expect([DEC.decode(await materialize(io.stderr)), io.exitCode]).toEqual([
      'jq: error (at /d/live.json:1): Expected separator between values at line 1, column 5\n',
      5,
    ])
    const [pairs] = await started('[., input]', '1\n2\n', { compact_output: true })
    if (pairs === null || pairs instanceof Uint8Array) throw new Error('jq did not stream')
    const first = await soon(pairs[Symbol.asyncIterator]().next())
    if (first === 'still waiting' || first.done === true) {
      throw new Error('jq waited on the rest of the input')
    }
    expect(DEC.decode(first.value)).toBe('[1,2]\n')
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

  it('ends a usage error with the hint jq 1.8 gives', () => {
    expect(() => namedArgs(view({ argjson: ['v', '1 2'] }))).toThrow(
      'jq: invalid JSON text passed to --argjson\n' +
        'Use jq --help for help with command-line options,\n' +
        'or see the jq manpage, or online docs at https://jqlang.org',
    )
  })

  it("reads an --argjson value as jq's parser does", () => {
    expect(namedArgs(view({ argjson: ['v', '{"a":1}'] }))).toEqual(new Map([['v', '{"a":1}']]))
    expect(namedArgs(view({ argjson: ['v', 'nan'] }))).toEqual(new Map([['v', 'nan']]))
    expect(() => namedArgs(view({ argjson: ['v', '1 2'] }))).toThrow(
      'jq: invalid JSON text passed to --argjson',
    )
  })
})

const MISSING = 'jq: error: Could not open file /d/nope.json: No such file or directory\n'

describe('jqGeneric over an input it cannot read', () => {
  it('reports an input that cannot be opened and reads past it', async () => {
    // jq reports the file, reads on, and its main loop stops after the
    // document the reader went on to (pinned: `jq . missing.json a.json`
    // prints a.json's first document only).
    expect(await ranOver(['/d/nope.json', '/d/four.json'], '.')).toEqual({
      stdout: '1\n',
      stderr: MISSING,
      exitCode: 2,
    })
    expect(await ranOver(['/d/four.json', '/d/nope.json', '/d/rows.jsonl'], '.')).toEqual({
      stdout: '1\n2\n3\n4\n{"a":1}\n',
      stderr: MISSING,
      exitCode: 2,
    })
  })

  it('exits 2 whatever the runs answered', async () => {
    expect(
      await ranOver(['/d/nope.json', '/d/four.json'], '. == 0', { exit_status: true }),
    ).toEqual({ stdout: 'false\n', stderr: MISSING, exitCode: 2 })
    expect(await ranOver(['/d/nope.json', '/d/four.json'], 'halt_error')).toEqual({
      stdout: '',
      stderr: `${MISSING}1\n`,
      exitCode: 2,
    })
  })

  it("reports a directory in jq's bare words", async () => {
    expect(await ranOver(['/d/dir', '/d/four.json'], '.')).toEqual({
      stdout: '1\n',
      stderr: 'jq: error: Is a directory\n',
      exitCode: 2,
    })
  })

  it('lets input read past a failed input to the next', async () => {
    // One that finds nothing more fails where the reader stopped, on the
    // failed file at line 0 (pinned).
    expect(await ranOver(['/d/nope.json', '/d/four.json'], 'input', { null_input: true })).toEqual({
      stdout: '1\n',
      stderr: MISSING,
      exitCode: 2,
    })
    expect(await ranOver(['/d/nope.json'], 'input', { null_input: true })).toEqual({
      stdout: '',
      stderr: `${MISSING}jq: error (at /d/nope.json:0): break\n`,
      exitCode: 2,
    })
  })

  it.each([
    ['rawfile', '/d/nope.json', 'No such file or directory'],
    ['slurpfile', '/d/nope.json', 'No such file or directory'],
    ['rawfile', '/d/dir', "It's a directory"],
    ['slurpfile', '/d/dir', "It's a directory"],
  ])("refuses a --%s file it cannot read (%s) in jq's words", async (option, path, reason) => {
    await expect(
      ranOver([], '$x', { null_input: true, [option]: ['x', path] }),
    ).rejects.toMatchObject({
      message: `jq: Bad JSON in --${option} x ${path}: Could not open ${path}: ${reason}`,
      exitCode: 2,
    })
  })
})
