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

// cmp's byte counts, byte rendering and diagnostics, pinned on GNU 9.1.
// Mirrors python/tests/commands/builtin/generic/test_cmp.py.

import { describe, expect, it } from 'vitest'
import { cmpGeneric, parseCount, parseSkip, visible } from './cmp.ts'
import { UsageError } from '../../errors.ts'
import { RAMVFS } from '../../../vfs/ram/ram.ts'
import { getTestParser } from '../../../workspace/fixtures/workspace_fixture.ts'
import { Workspace } from '../../../workspace/workspace/workspace.ts'
import { MountMode, PathSpec } from '../../../types.ts'
import { materialize } from '../../../io/types.ts'
import { eisdir, enoent } from '../../../utils/errors.ts'
import type { CommandOpts } from '../../config.ts'

const DEC = new TextDecoder()
const ENC = new TextEncoder()
const P1 = new PathSpec({ virtual: '/F/one', directory: '/F', vfsPath: 'one' })
const P2 = new PathSpec({ virtual: '/F/two', directory: '/F', vfsPath: 'two' })
const DASH = new PathSpec({ virtual: '/F/-', directory: '/F', vfsPath: '-', rawPath: '-' })
const DEV_STDIN = new PathSpec({ virtual: '/dev/stdin', directory: '/dev', vfsPath: 'stdin' })

function bytes(...values: number[]): Uint8Array {
  return new Uint8Array(values)
}

async function run(
  first: Uint8Array,
  second: Uint8Array,
  flags: Record<string, unknown> = {},
): Promise<{ out: string; err: string; code: number }> {
  const stream = (p: PathSpec): AsyncIterable<Uint8Array> => {
    const held = p.virtual === P1.virtual ? first : second
    return (async function* gen() {
      await Promise.resolve()
      yield held
    })()
  }
  const opts = { flags, stdin: null } as unknown as CommandOpts
  const [src, io] = await cmpGeneric([P1, P2], [], opts, stream)
  return {
    out: DEC.decode(await materialize(src)),
    err: DEC.decode(await materialize(io.stderr)),
    code: io.exitCode,
  }
}

describe('parseCount', () => {
  it.each([
    ['4', 4],
    ['1K', 1024],
    ['1k', 1024],
    ['1kB', 1000],
    ['1kiB', 1024],
    ['1M', 1024 * 1024],
    ['0Z', 0],
    ['010', 8],
    ['0x400', 1024],
    ['+1010', 1010],
    [' 1', 1],
    ['7E', 7 * 1024 ** 6],
  ])('takes %j', (raw, value) => {
    expect(parseCount(raw, '--bytes')).toBe(value)
  })

  // diffutils 3.10 takes no od block or char suffix, no Q or R (newer than
  // its gnulib), and caps a count at INTMAX: each is an invalid value, exit 2.
  it.each([
    '1b',
    '1B',
    '1c',
    '1w',
    '1m',
    '1g',
    '1t',
    '1Q',
    '0Q',
    '1 ',
    '-1',
    '9223372036854775808',
    '8E',
    '1Z',
    '1Y',
  ])('refuses %j', (raw) => {
    expect(() => parseCount(raw, '--bytes')).toThrow(UsageError)
  })

  it('names the long option it was given', () => {
    // GNU says `invalid --bytes value` for -n and `invalid
    // --ignore-initial value` for -i, exit 2. diffutils routes the
    // Try-help line through error(), so it carries the `cmp: ` prefix
    // that coreutils' bare hint does not.
    let caught: unknown
    try {
      parseCount('abc', '--bytes')
    } catch (err) {
      caught = err
    }
    expect(caught).toBeInstanceOf(UsageError)
    expect((caught as UsageError).message).toBe(
      "cmp: invalid --bytes value 'abc'\ncmp: Try 'cmp --help' for more information.",
    )
    expect((caught as UsageError).exitCode).toBe(2)
  })
})

describe('parseSkip', () => {
  it('takes one count for both files', () => {
    expect(parseSkip('3')).toEqual([3, 3])
  })

  it.each([
    ['1b:1', '1b:1'],
    ['1:1b', '1b'],
    ['1:abc', 'abc'],
    ['abc:1', 'abc:1'],
    ['1:2:3', '2:3'],
    ['1:', ''],
    [':1', ':1'],
    [':', ':'],
  ])('names the operand from where it stopped: %s', (raw, named) => {
    // GNU prints the operand from the position xstrtoumax was reading,
    // so a bad SKIP1 names the whole pair and a bad SKIP2 names only
    // itself. A colon is the one character the first count may stop on.
    let caught: unknown
    try {
      parseSkip(raw)
    } catch (err) {
      caught = err
    }
    expect(caught).toBeInstanceOf(UsageError)
    expect((caught as UsageError).message.split('\n')[0]).toBe(
      `cmp: invalid --ignore-initial value '${named}'`,
    )
  })

  it('takes a colon pair for one each', () => {
    expect(parseSkip('0:3')).toEqual([0, 3])
    expect(parseSkip('1K:2')).toEqual([1024, 2])
  })
})

describe('visible', () => {
  it.each([
    ['b'.charCodeAt(0), 'b'],
    [9, '^I'],
    [1, '^A'],
    [127, '^?'],
    [0xc3, 'M-C'],
    [0xa9, 'M-)'],
    [0x80, 'M-^@'],
  ])('renders %i the cat -v way', (byte, rendered) => {
    expect(visible(byte)).toBe(rendered)
  })
})

describe('cmpGeneric', () => {
  it('pads the octal to three columns under -l', async () => {
    const r = await run(bytes(97, 1, 99), bytes(97, 127, 99), { verbose: true })
    expect(r.out).toBe('2   1 177\n')
  })
})

async function runWithStdin(
  paths: PathSpec[],
  stdin: string,
  second: string,
  flags: Record<string, unknown> = {},
): Promise<{ out: string; err: string; code: number }> {
  const stream = (p: PathSpec): AsyncIterable<Uint8Array> => {
    expect(p.virtual).toBe(P2.virtual)
    return (async function* gen() {
      await Promise.resolve()
      yield ENC.encode(second)
    })()
  }
  const opts = { flags, stdin: ENC.encode(stdin) } as unknown as CommandOpts
  const [src, io] = await cmpGeneric(paths, [], opts, stream)
  return {
    out: DEC.decode(await materialize(src)),
    err: DEC.decode(await materialize(io.stderr)),
    code: io.exitCode,
  }
}

describe('cmpGeneric with stdin', () => {
  it('reads /dev/stdin from stdin and names it as typed', async () => {
    const r = await runWithStdin([DEV_STDIN, P2], 'one\n', 'two\n')
    expect(r).toEqual({ out: '/dev/stdin /F/two differ: char 1, line 1\n', err: '', code: 1 })
  })

  it('takes two stdin operands at one offset as equal unread', async () => {
    const stream = (p: PathSpec): AsyncIterable<Uint8Array> => {
      throw new Error(`read ${p.virtual}`)
    }
    const opts = {
      flags: { ignore_initial: '1' },
      stdin: ENC.encode('abc'),
    } as unknown as CommandOpts
    const [src, io] = await cmpGeneric([DASH, DEV_STDIN], [], opts, stream)
    expect([src, io.exitCode, io.stderr]).toEqual([null, 0, null])
  })

  it.each([
    [false, 'cmp: EOF on - which is empty\ncmp: -: Bad file descriptor\n'],
    [true, 'cmp: -: Bad file descriptor\n'],
  ])(
    'shares one descriptor between two stdin operands skipped apart (-s %s)',
    async (silent, err) => {
      // diffutils 3.10 skips on the one descriptor twice, the first file reads
      // what is left and the second nothing, and closing it again fails:
      // `cmp - - 1 2 < a.txt`.
      const stream = (p: PathSpec): AsyncIterable<Uint8Array> => {
        throw new Error(`read ${p.virtual}`)
      }
      const opts = {
        flags: silent ? { quiet: true } : {},
        stdin: ENC.encode('hello\n'),
      } as unknown as CommandOpts
      const [src, io] = await cmpGeneric([DASH, DASH], ['1', '2'], opts, stream)
      expect([src, DEC.decode(await materialize(io.stderr)), io.exitCode]).toEqual([null, err, 2])
    },
  )

  it.each([false, true])('says which is empty for an empty file (-l %s)', async (verbose) => {
    const r = await run(new Uint8Array(0), ENC.encode('x'), verbose ? { verbose: true } : {})
    expect([r.err, r.code]).toEqual(['cmp: EOF on /F/one which is empty\n', 1])
  })

  it('pads -l offsets to the smaller regular file', async () => {
    const r = await run(ENC.encode('a'.repeat(11)), ENC.encode('b' + 'a'.repeat(12)), {
      verbose: true,
    })
    expect(r.out).toBe(' 1 141 142\n')
  })

  it('names the operands as typed', async () => {
    const one = new PathSpec({ virtual: '/F/one', directory: '/F', vfsPath: 'one', rawPath: 'one' })
    const two = new PathSpec({ virtual: '/F/two', directory: '/F', vfsPath: 'two', rawPath: 'two' })
    const stream = (p: PathSpec): AsyncIterable<Uint8Array> =>
      (async function* gen() {
        await Promise.resolve()
        yield ENC.encode(p.virtual === one.virtual ? 'a' : 'b')
      })()
    const opts = { flags: {}, stdin: null } as unknown as CommandOpts
    const [src] = await cmpGeneric([one, two], [], opts, stream)
    expect(DEC.decode(await materialize(src))).toBe('one two differ: char 1, line 1\n')
  })
})

// `cmp -n` quotes the value but does NOT escape it. diffutils is not
// coreutils: it interpolates the bytes with a plain `%s` inside the quotes
// rather than passing them through gnulib's `quote()`, so a control byte, a
// backslash and a single quote all reach stderr as themselves. Measured
// against GNU diffutils' cmp under `LC_ALL=C` with a raw `bytes` argv:
// `cmp -n 1é` reports `invalid --bytes value '1é'` and `cmp -n "1'"`
// reports `'1''`, where the coreutils clauses next door would say
// `'1\303\251'` and `'1\''`. This asymmetry is deliberate; do not "fix" it
// by routing this clause through quote(). Mirrors test_cmp.py.
describe('parseCount leaves the value unescaped', () => {
  it.each([['1é'], ['1\x01'], ['1\r'], ["1'"], ['1\\']])('keeps %j as typed', (value) => {
    expect(() => parseCount(value, '--bytes')).toThrow(
      new UsageError(
        `cmp: invalid --bytes value '${value}'\n` + "cmp: Try 'cmp --help' for more information.",
        2,
      ),
    )
  })
})

describe('cmpGeneric -s', () => {
  // diffutils 3.10 opens both operands, then reads: -s drops only a failed
  // open, a directory opens and fails reading, and one file named twice at
  // the same offset is equal unread. Mirrors test_cmp.py.
  it.each([
    [['dir', 'one'], true, 2, 'cmp: dir: Is a directory\n'],
    [['one', 'dir'], true, 2, 'cmp: dir: Is a directory\n'],
    [['dir', 'nope'], true, 2, ''],
    [['dir', 'nope'], false, 2, 'cmp: nope: No such file or directory\n'],
    [['dir', 'dir'], false, 0, ''],
  ] as const)(
    'reads a directory after both opens: %j silent %s',
    async (names, silent, code, want) => {
      async function* read(p: PathSpec): AsyncIterable<Uint8Array> {
        await Promise.resolve()
        if (p.virtual === '/F/dir') throw eisdir(p)
        if (p.virtual.endsWith('nope')) throw enoent(p)
        yield ENC.encode('a')
      }
      const paths = names.map(
        (n) => new PathSpec({ virtual: `/F/${n}`, directory: '/F', vfsPath: n, rawPath: n }),
      )
      const opts = { flags: silent ? { quiet: true } : {}, stdin: null } as unknown as CommandOpts
      const [, io] = await cmpGeneric(paths, [], opts, read)
      expect([DEC.decode(await materialize(io.stderr)), io.exitCode]).toEqual([want, code])
    },
  )
})

async function runSkips(
  texts: string[],
  flags: Record<string, unknown> = {},
): Promise<[string, number]> {
  const stream = (p: PathSpec): AsyncIterable<Uint8Array> =>
    (async function* gen() {
      await Promise.resolve()
      yield ENC.encode(p.virtual === P1.virtual ? 'xhello\n' : 'hello\n')
    })()
  const opts = { flags, stdin: null } as unknown as CommandOpts
  const [src, io] = await cmpGeneric([P1, P2], texts, opts, stream)
  return [DEC.decode(await materialize(src)), io.exitCode]
}

describe('the skip operands', () => {
  // Mirrors python's test_the_skip_operands_read_as_i_and_keep_the_larger.
  const differ = '/F/one /F/two differ: char 1, line 1\n'
  it.each([
    // SKIP1 skips the first file only; SKIP2 the second.
    [['1'], {}, '', 0],
    [['0', '1'], {}, differ, 1],
    [['1', '1'], {}, differ, 1],
    // Base 0 and cmp's own suffixes, as -i reads them.
    [['0x1'], {}, '', 0],
    [['01'], {}, '', 0],
    [['+1'], {}, '', 0],
    // Each file keeps the larger of -i's skip and its operand's.
    [['0', '2'], { ignore_initial: '1' }, differ, 1],
    [['0', '0'], { ignore_initial: '1:0' }, '', 0],
  ] as const)('%j with %j', async (texts, flags, out, code) => {
    expect(await runSkips([...texts], flags)).toEqual([out, code])
  })

  it.each([
    [['1', 'y'], "cmp: invalid --ignore-initial value 'y'"],
    [[''], "cmp: invalid --ignore-initial value ''"],
    [['1:2'], "cmp: invalid --ignore-initial value '1:2'"],
    [['1 '], "cmp: invalid --ignore-initial value '1 '"],
    [['9223372036854775808'], "cmp: invalid --ignore-initial value '9223372036854775808'"],
    [['y', '1', '2'], "cmp: invalid --ignore-initial value 'y'"],
  ] as const)('refuses %j', async (texts, message) => {
    await expect(runSkips([...texts])).rejects.toThrow(
      new UsageError(`${message}\ncmp: Try 'cmp --help' for more information.`),
    )
  })

  it.each([
    [[], 'cmp'],
    [['-s'], '-s'],
    [['-n', '5'], '5'],
    [['-i3'], '-i3'],
    [['--ignore-initial=3'], '--ignore-initial=3'],
    [['-s', '--'], '--'],
  ] as const)('names the last word of %j when no operand is given', async (argv, after) => {
    const opts = { flags: {}, stdin: null, argv } as unknown as CommandOpts
    const stream = (): AsyncIterable<Uint8Array> => {
      throw new Error('read')
    }
    await expect(cmpGeneric([], [], opts, stream)).rejects.toThrow(
      new UsageError(
        `cmp: missing operand after '${after}'\ncmp: Try 'cmp --help' for more information.`,
      ),
    )
  })
})

describe('cmp across mounts', () => {
  // The relay reads the skips too, and refuses a bad one as cmp's own result,
  // so the rest of the line still runs. Mirrors python's
  // test_the_skips_reach_a_cmp_across_mounts.
  it.each([
    ['cmp /data/x /other/f 1; echo rc=$?', 'rc=0\n', ''],
    [
      'cmp /data/x /other/f z; echo rc=$?',
      'rc=2\n',
      "cmp: invalid --ignore-initial value 'z'\ncmp: Try 'cmp --help' for more information.\n",
    ],
  ])('%s', async (line, out, err) => {
    const ws = new Workspace(
      { '/data/': new RAMVFS(), '/other/': new RAMVFS() },
      { mode: MountMode.WRITE, shellParser: await getTestParser() },
    )
    await ws.shell("printf 'xro\\n' > /data/x && printf 'ro\\n' > /other/f")
    const r = await ws.shell(line)
    expect([DEC.decode(r.stdout), DEC.decode(r.stderr)]).toEqual([out, err])
    await ws.close()
  })
})
