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
import { yieldBytes } from '../../../io/stream.ts'
import { materialize, type ByteSource, type IOResult } from '../../../io/types.ts'
import { PathSpec } from '../../../types.ts'
import { eisdir, enoent } from '../../../utils/errors.ts'
import { type CommandOpts } from '../../config.ts'
import { helpPage, versionLine } from '../../spec/standard.ts'
import { specOf } from '../../spec/builtins.ts'
import { FlagView } from '../../spec/flag_view.ts'
import { parseCommand, parseToKwargs } from '../../spec/parser.ts'
import {
  exitCode,
  indentWidth,
  inputName,
  jqGeneric,
  optionRefusal,
  parseFlags,
  positionalValue,
  readOptions,
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
  '/d/nul.jq': '.\u0000x',
  '/d/-': '42\n',
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
  stream: typeof read = read,
): Promise<Ran> {
  const opts = {
    stdin: null,
    flags: { compact_output: true, ...flags },
    filetypeFns: null,
    cwd: '/',
    vfs: { kind: 'ram' } as never,
  } as CommandOpts
  const specs = paths.map((path) => PathSpec.fromStrPath(path))
  const result = await jqGeneric(specs, [program], opts, stream)
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

const HINT =
  'Use jq --help for help with command-line options,\n' +
  'or see the jq manpage, or online docs at https://jqlang.org'

/** A jq line's flags as the parser leaves them, with the order they were typed in. */
function parsedFlags(...words: string[]): CommandOpts['flags'] {
  return parseToKwargs(parseCommand(specOf('jq'), words, '/', 'jq'))
}

function toSpec(value: string): PathSpec {
  return PathSpec.fromStrPath(value)
}

async function unread(path: PathSpec): Promise<Uint8Array> {
  await Promise.resolve()
  throw new Error(`${path.virtual} should not be read`)
}

/** The options a walk read to, where it cannot have answered --help. */
function asOptions(result: JqOptions | Uint8Array): JqOptions {
  if (result instanceof Uint8Array) throw new Error('the walk answered --help or --version')
  return result
}

/** What a jq line's option walk answers, its flag files read with `reader`. */
async function walkLine(
  words: readonly string[],
  reader: (path: PathSpec) => Promise<Uint8Array>,
): Promise<JqOptions | Uint8Array> {
  const parsed = parseCommand(specOf('jq'), [...words], '/', 'jq')
  const flags = parseToKwargs(parsed)
  const fl = new FlagView(flags, specOf('jq'))
  return readOptions(fl, parsed.texts(), 'from_file' in flags, toSpec, reader)
}

/** The options a jq line reads to, its flag files read with `reader`. */
async function readLine(
  words: readonly string[],
  reader: (path: PathSpec) => Promise<Uint8Array>,
): Promise<JqOptions> {
  return asOptions(await walkLine(words, reader))
}

/** The options a jq line reads to, its flag files read off FILES. */
async function options(...words: string[]): Promise<JqOptions> {
  return readLine(words, (path) => materialize(read(path)))
}

/** The bindings a flag record makes, where no file may be read. */
async function bound(
  flags: Record<string, string | boolean | number | string[]>,
): Promise<ReadonlyMap<string, string>> {
  return asOptions(await readOptions(view(flags), [], false, toSpec, unread)).namedArgs
}

/** How jq lays an output out under these options. */
function layout(opts: JqOptions): string | number {
  if (opts.compact) return 'compact'
  return opts.tab ? 'tab' : opts.indent
}

describe('parseFlags', () => {
  it('reads -j and --raw-output0 as implying -r', () => {
    expect(parseFlags(view({ join_output: true })).rawOutput).toBe(true)
    expect(parseFlags(view({ raw_output0: true })).rawOutput).toBe(true)
  })
})

describe('indentWidth', () => {
  it.each([
    ['3', 3],
    ['+3', 3],
    ['07', 7],
    ['-0', 0],
    ['0', 0],
    ['-1', -1],
  ] as const)("reads %j as jq's strtol does", (word, width) => {
    expect(indentWidth(word)).toBe(width)
  })

  it.each(['x', '2x', '', ' 3', '3 ', '3\n', '1.5', '0x3', '08', '-2', '99999999999999999999'])(
    "refuses %j in jq's words",
    (word) => {
      expect(() => indentWidth(word)).toThrow(
        `jq: --indent takes a number between -1 and 7\n${HINT}`,
      )
    },
  )

  it.each([
    ['', '7', 7],
    ['+', '3', 3],
    ['-', '1', -1],
    ['-', '0', 0],
    ['', '0', 0],
  ] as const)('accepts arbitrary leading zeroes before %s%s', (sign, digit, width) => {
    expect(indentWidth(sign + '0'.repeat(5000) + digit)).toBe(width)
  })

  it.each([
    ['', '9'],
    ['-', '9'],
    ['+', '9'],
    ['', '0'],
  ])("refuses oversized indent starting with %s%s in jq's words", (sign, digits) => {
    expect(() => indentWidth(sign + digits.repeat(5000) + '8')).toThrow(
      `jq: --indent takes a number between -1 and 7\n${HINT}`,
    )
  })
})

describe('readOptions', () => {
  it('reads --indent -1 as tab indentation', async () => {
    const opts = asOptions(await readOptions(view({ indent: '-1' }), [], false, toSpec, unread))
    expect(opts.tab).toBe(true)
    expect(opts.indent).toBe(2)
  })

  it.each([
    [['-c', '--tab'], 'tab'],
    [['--tab', '-c'], 'compact'],
    [['--indent', '3', '-c'], 'compact'],
    [['-c', '--indent', '3'], 3],
    [['--tab', '--indent', '3'], 3],
    [['--indent', '3', '--tab'], 'tab'],
    [['--indent', '-1', '-c'], 'compact'],
    [['-c', '--indent', '-1'], 'tab'],
    [['-cr', '--tab'], 'tab'],
    [['--tab', '-rc'], 'compact'],
    [['--indent', '2', '--indent', '5'], 5],
  ] as const)('lets the last layout option typed win: %j', async (words, expected) => {
    expect(layout(await options(...words, '.'))).toBe(expected)
  })

  it('reads a later --indent word too', async () => {
    await expect(options('--indent', '2', '--indent', 'x', '.')).rejects.toThrow(
      '--indent takes a number',
    )
  })

  it('binds each --arg name to a string', async () => {
    expect(await bound({ arg: ['a', '1', 'b', 'x"y'] })).toEqual(
      new Map([
        ['a', '"1"'],
        ['b', '"x\\"y"'],
      ]),
    )
  })

  it('keeps an --argjson value as the text jq reads', async () => {
    expect(await bound({ argjson: ['v', ' {"b":1.000,"1":2} '] })).toEqual(
      new Map([['v', '{"b":1.000,"1":2}']]),
    )
  })

  it('refuses invalid JSON', async () => {
    await expect(bound({ argjson: ['v', 'nope'] })).rejects.toThrow(/invalid JSON text/)
  })

  it('keeps the bindings in the order they were typed in', async () => {
    const opts = await options(
      '-n',
      '--slurpfile',
      's',
      '/d/four.json',
      '--arg',
      'a',
      '1',
      '--rawfile',
      'r',
      '/d/one.json',
      '--argjson',
      'b',
      '2',
      '$ARGS.named',
    )
    expect([...opts.namedArgs]).toEqual([
      ['s', '[1,2,3,4]'],
      ['a', '"1"'],
      ['r', '"1"'],
      ['b', '2'],
    ])
  })

  it.each([
    [['--argjson', 'v', '1', '--argjson', 'v', '2'], '1'],
    [['--arg', 'v', '1', '--argjson', 'v', '2'], '"1"'],
    [['--rawfile', 'v', '/d/one.json', '--arg', 'v', '2'], '"1"'],
    [['--slurpfile', 'v', '/d/two.json', '--rawfile', 'v', '/d/one.json'], '[2]'],
  ] as const)('lets the first binding of a name win: %j', async (words, text) => {
    expect((await options('-n', ...words, '$v')).namedArgs).toEqual(new Map([['v', text]]))
  })

  it.each([
    [['--argjson', 'v', 'nope']],
    [['--rawfile', 'v', '/d/missing.txt']],
    [['--slurpfile', 'v', '/d/bad.json']],
  ] as const)('never reads a binding of a taken name: %j', async (words) => {
    const opts = await readLine(['-n', '--arg', 'v', '1', ...words, '$v'], unread)
    expect(opts.namedArgs).toEqual(new Map([['v', '"1"']]))
  })

  it.each([
    [['--indent', 'x', '--argjson', 'a', 'nope'], 'jq: --indent takes'],
    [['--argjson', 'a', 'nope', '--indent', 'x'], 'jq: invalid JSON text'],
    [['--argjson', 'a', 'nope', '--slurpfile', 'b', '/d/missing.json'], 'jq: invalid JSON text'],
    [
      ['--slurpfile', 'b', '/d/missing.json', '--argjson', 'a', 'nope'],
      'jq: Bad JSON in --slurpfile b /d/missing.json',
    ],
  ] as const)('reports the first option jq refuses: %j', async (words, refusal) => {
    await expect(options('-n', ...words, '1')).rejects.toThrow(refusal)
  })

  it('is what jqGeneric reads the flags it is handed with', async () => {
    const opts = {
      stdin: null,
      flags: parsedFlags(
        '-n',
        '--tab',
        '-c',
        '--argjson',
        'b',
        '1',
        '--arg',
        'a',
        '2',
        '--arg',
        'b',
        '3',
        '$ARGS.named',
      ),
      filetypeFns: null,
      cwd: '/',
      vfs: { kind: 'ram' } as never,
    } as CommandOpts
    const result = await jqGeneric([], ['$ARGS.named'], opts, read)
    if (result === null) throw new Error('jq returned no result')
    const [out, io] = result
    expect(DEC.decode(await materialize(out))).toBe('{"b":1,"a":"2"}\n')
    expect(io.exitCode).toBe(0)
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

describe('positionalValue', () => {
  it('reads an operand under --args as a string', () => {
    expect(positionalValue('args', '1')).toBe('"1"')
  })

  it('keeps each operand under --jsonargs as the text jq reads', () => {
    expect(positionalValue('jsonargs', '1.0')).toBe('1.0')
    expect(positionalValue('jsonargs', '{"b":1,"1":2}')).toBe('{"b":1,"1":2}')
  })

  it("refuses invalid JSON under --jsonargs in jq's words", () => {
    expect(() => positionalValue('jsonargs', 'nope')).toThrow(
      `jq: invalid JSON text passed to --jsonargs\n${HINT}`,
    )
  })
})

describe('readOptions over --args and --jsonargs', () => {
  it.each([
    [
      ['--args', 'a', '--jsonargs', '1', '--args', 'b'],
      ['"a"', '1', '"b"'],
    ],
    [
      ['--jsonargs', '1', '--args', 'a'],
      ['1', '"a"'],
    ],
    [['--args', '--jsonargs', '1'], ['1']],
    [
      ['--args', '{', '--jsonargs', '1'],
      ['"{"', '1'],
    ],
    [
      ['/d/a.json', '--args', 'x', '/d/b.json'],
      ['"x"', '"/d/b.json"'],
    ],
    [
      ['--jsonargs', '1', '--arg', 'x', 'y', '2'],
      ['1', '2'],
    ],
    [
      ['--args', '--', '-x', '--jsonargs'],
      ['"-x"', '"--jsonargs"'],
    ],
    [['/d/a.json'], []],
  ] as const)(
    'files each operand by the mode typed last before it: %j',
    async (words, positional) => {
      expect((await options('-n', '.', ...words)).positionalArgs).toEqual(positional)
    },
  )

  it('takes the program first whatever the mode', async () => {
    const opts = await options('-n', '--jsonargs', '.', '1', '--args', '2', '--jsonargs', '3')
    expect(opts.positionalArgs).toEqual(['1', '"2"', '3'])
  })

  it('leaves every operand to the modes when -f gave the program', async () => {
    const opts = await options(
      '-n',
      '-f',
      '/d/prog.jq',
      '/d/a.json',
      '--args',
      'b',
      '--jsonargs',
      '2',
    )
    expect(opts.positionalArgs).toEqual(['"b"', '2'])
  })

  it.each([
    [['--jsonargs', 'nope', '--indent', 'x'], 'jq: invalid JSON text passed to --jsonargs'],
    [['--indent', 'x', '--jsonargs', 'nope'], 'jq: --indent takes'],
    [
      ['--jsonargs', 'nope', '--argjson', 'a', 'nope'],
      'jq: invalid JSON text passed to --jsonargs',
    ],
    [['--argjson', 'a', 'nope', '--jsonargs', 'nope'], 'jq: invalid JSON text passed to --argjson'],
    [
      ['--jsonargs', 'nope', '--slurpfile', 'b', '/d/missing.json'],
      'jq: invalid JSON text passed to --jsonargs',
    ],
    [
      ['--slurpfile', 'b', '/d/missing.json', '--jsonargs', 'nope'],
      'jq: Bad JSON in --slurpfile b /d/missing.json',
    ],
  ] as const)('refuses a --jsonargs operand where it was typed: %j', async (words, refusal) => {
    await expect(options('-n', '.', ...words)).rejects.toThrow(refusal)
  })

  it.each([
    [{ args: true }, false, ['.', 'a', '1'], ['"a"', '"1"']],
    [{ args: true }, true, ['a', 'b'], ['"a"', '"b"']],
    [{ args: true, jsonargs: true }, false, ['.', '1'], ['1']],
    [{ jsonargs: true, args: true }, false, ['.', '1'], ['"1"']],
    [{}, false, ['.', 'a'], []],
  ] as const)(
    'files the operands of a record with no tape after every option: %j',
    async (flags, hasProgramFile, texts, positional) => {
      const opts = asOptions(await readOptions(view(flags), texts, hasProgramFile, toSpec, unread))
      expect(opts.positionalArgs).toEqual(positional)
    },
  )

  it('still reads an input file typed before --args', async () => {
    const parsed = parseCommand(
      specOf('jq'),
      ['-c', '[., $ARGS.positional]', '/d/one.json', '--args', '/d/two.json'],
      '/',
      'jq',
    )
    const opts = {
      stdin: null,
      flags: parseToKwargs(parsed),
      filetypeFns: null,
      cwd: '/',
      vfs: { kind: 'ram' } as never,
    } as CommandOpts
    const specs = parsed.paths().map((path) => PathSpec.fromStrPath(path))
    const result = await jqGeneric(specs, parsed.texts(), opts, read)
    if (result === null) throw new Error('jq returned no result')
    const [out, io] = result
    expect(DEC.decode(await materialize(out))).toBe('[1,["/d/two.json"]]\n')
    expect(io.exitCode).toBe(0)
  })

  it('hands dash words to jq as the program and its values', async () => {
    const parsed = parseCommand(
      specOf('jq'),
      ['-n', '-c', '-$ARGS.positional[0], $ARGS.positional', '--jsonargs', '-1', '--args', '-.'],
      '/',
      'jq',
    )
    const opts = {
      stdin: null,
      flags: parseToKwargs(parsed),
      filetypeFns: null,
      cwd: '/',
      vfs: { kind: 'ram' } as never,
    } as CommandOpts
    const result = await jqGeneric([], parsed.texts(), opts, read)
    if (result === null) throw new Error('jq returned no result')
    const [out, io] = result
    expect(DEC.decode(await materialize(out))).toBe('1\n[-1,"-."]\n')
    expect(io.exitCode).toBe(0)
  })
})

describe('jq flag-file readers', () => {
  it.each([
    ['from_file', '42\n'],
    ['rawfile', '"42\\n"\n'],
    ['slurpfile', '[42]\n'],
  ])('reads a dash %s from the backend without a dispatcher', async (option, expected) => {
    const path = new PathSpec({ virtual: '/d/-', directory: '/d', vfsPath: '-', rawPath: '-' })
    const opts = {
      stdin: ENC.encode('99\n'),
      flags: {
        null_input: true,
        compact_output: true,
        [option]: option === 'from_file' ? path : ['x', path],
      },
      filetypeFns: null,
      cwd: '/d',
      vfs: { kind: 'ram' } as never,
    } as CommandOpts
    const result = await jqGeneric([], ['$x'], opts, read)
    if (result === null) throw new Error('jq returned no result')
    const [out, io] = result
    expect(DEC.decode(await materialize(out))).toBe(expected)
    expect(io.exitCode).toBe(0)
    expect(await materialize(io.stderr)).toEqual(new Uint8Array())
  })

  describe.each(['from_file', 'rawfile', 'slurpfile'])('%s consumes stdin', (option) => {
    describe.each([false, true])('streamed=%s', (streamed) => {
      it.each([null, '-', '/dev/stdin'])('does not replay stdin for input %s', async (operand) => {
        const path = PathSpec.fromStrPath('/dev/stdin')
        const stdin = ENC.encode('99\n')
        const opts = {
          stdin: streamed ? yieldBytes(stdin) : stdin,
          flags: { [option]: option === 'from_file' ? path : ['x', path] },
          filetypeFns: null,
          cwd: '/',
          vfs: { kind: 'ram' } as never,
        } as CommandOpts
        const paths =
          operand === null
            ? []
            : [
                new PathSpec({
                  virtual: '/dev/stdin',
                  directory: '/dev',
                  vfsPath: 'stdin',
                  rawPath: operand,
                }),
              ]
        const result = await jqGeneric(paths, ['.'], opts, read)
        if (result === null) throw new Error('jq returned no result')
        const [out, io] = result
        expect(await materialize(out)).toEqual(new Uint8Array())
        expect(io.exitCode).toBe(0)
        expect(await materialize(io.stderr)).toEqual(new Uint8Array())
      })
    })
  })
})

describe("jq's option loop", () => {
  it.each([
    ['-x', 'Unknown option -x'],
    ['--indent=3', 'Unknown option --indent=3'],
    ['--arg', '--arg takes two parameters (e.g. --arg varname value)'],
    ['--slurpfile', '--slurpfile takes two parameters (e.g. --slurpfile varname filename)'],
    ['--indent', '--indent takes one parameter'],
  ])('words a refused %s as jq does', (word, line) => {
    expect(optionRefusal(word).message).toBe(`jq: ${line}\n${HINT}`)
  })

  it("prints jq's short usage for an -f the line ends at", () => {
    const refusal = optionRefusal('-f')
    expect(refusal.message.startsWith('jq - commandline JSON processor [version 1.8.2]\n')).toBe(
      true,
    )
    expect(refusal.message.endsWith('For listing the command options, use jq --help.')).toBe(true)
    expect(refusal.exitCode).toBe(2)
  })

  // jq 1.8.2's loop stops at the first word it cannot take, so an option the
  // parser refused waits its turn behind a bad value typed before it.
  it.each([
    [['.', '--jsonargs', '{', '--bogus'], 'invalid JSON text passed to --jsonargs'],
    [['.', '--bogus', '--jsonargs', '{'], 'Unknown option --bogus'],
    [['.', '--indent', '9', '--bogus'], '--indent takes a number between -1 and 7'],
    [['.', '--bogus', '--indent', '9'], 'Unknown option --bogus'],
    [['.', '--argjson', 'x', '{', '-Z'], 'invalid JSON text passed to --argjson'],
  ])('reports the first refusal typed in %j', async (words, first) => {
    await expect(walkLine(['-n', ...words], unread)).rejects.toThrow(`jq: ${first}\n${HINT}`)
  })

  it('answers --help and --version where the loop reaches them', async () => {
    const help = ENC.encode(helpPage('jq', specOf('jq')))
    expect(await walkLine(['--help', '--bogus'], unread)).toEqual(help)
    expect(await walkLine(['-hx'], unread)).toEqual(help)
    expect(await walkLine(['-n', '.', '-V', '--jsonargs', '{'], unread)).toEqual(
      ENC.encode(versionLine('jq')),
    )
    await expect(walkLine(['--bogus', '--help'], unread)).rejects.toThrow('Unknown option --bogus')
    await expect(walkLine(['-n', '.', '--jsonargs', '{', '-V'], unread)).rejects.toThrow(
      'invalid JSON text passed to --jsonargs',
    )
  })

  /** Run a jq line whose -f file is read off FILES. */
  async function ranProgramFile(...words: string[]): Promise<Ran> {
    const opts = {
      stdin: null,
      flags: parsedFlags(...words),
      filetypeFns: null,
      cwd: '/',
      vfs: { kind: 'ram' } as never,
    } as CommandOpts
    const result = await jqGeneric([], [], opts, read)
    if (result === null) throw new Error('jq returned no result')
    const [out, io] = result
    return {
      stdout: DEC.decode(await materialize(out)),
      stderr: DEC.decode(await materialize(io.stderr)),
      exitCode: io.exitCode,
    }
  }

  it('reads the program file after the option loop', async () => {
    await expect(ranProgramFile('-n', '-f', '/d/missing.jq', '--bogus')).rejects.toThrow(
      'Unknown option --bogus',
    )
    const missing = await ranProgramFile('-n', '-f', '/d/missing.jq')
    expect(missing.exitCode).toBe(2)
    expect(missing.stderr).toContain('Could not open')
  })

  it('refuses a program file holding NUL', async () => {
    expect(await ranProgramFile('-n', '-f', '/d/nul.jq')).toEqual({
      stdout: '',
      stderr: 'jq: program file contains NUL bytes\n',
      exitCode: 2,
    })
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

  it('closes the input it stopped in at a parse error', async () => {
    const closed: string[] = []
    async function* tracked(path: PathSpec): AsyncIterable<Uint8Array> {
      try {
        yield* read(path)
      } finally {
        closed.push(path.virtual)
      }
    }
    const result = await ranOver(['/d/mid.json', '/d/a.json'], '.', {}, tracked)
    expect([result.stdout, result.exitCode]).toEqual(['1\n', 5])
    expect(closed).toEqual(['/d/mid.json'])
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

  it('ends a usage error with the hint jq 1.8 gives', async () => {
    await expect(bound({ argjson: ['v', '1 2'] })).rejects.toThrow(
      `jq: invalid JSON text passed to --argjson\n${HINT}`,
    )
  })

  it("reads an --argjson value as jq's parser does", async () => {
    expect(await bound({ argjson: ['v', '{"a":1}'] })).toEqual(new Map([['v', '{"a":1}']]))
    expect(await bound({ argjson: ['v', 'nan'] })).toEqual(new Map([['v', 'nan']]))
    await expect(bound({ argjson: ['v', '1 2'] })).rejects.toThrow(
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
