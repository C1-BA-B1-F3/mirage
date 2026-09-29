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
  it('takes digits and GNU size suffixes', () => {
    expect(parseCount('4', '--bytes')).toBe(4)
    expect(parseCount('1K', '--bytes')).toBe(1024)
    expect(parseCount('1k', '--bytes')).toBe(1024)
    expect(parseCount('1kB', '--bytes')).toBe(1000)
    expect(parseCount('1kiB', '--bytes')).toBe(1024)
    expect(parseCount('1M', '--bytes')).toBe(1024 * 1024)
  })

  it.each(['1b', '1B', '1c', '1w', '1m', '1g', '1t'])(
    'rejects %s, a letter od takes and cmp does not',
    (raw) => {
      // diffutils 3.10 lists only kB/K/MB/M/... : no block or char
      // suffixes, and lowercase only as far as k. `cmp -n 1b` is exit 2,
      // where od would read it as 512 bytes.
      expect(() => parseCount(raw, '--bytes')).toThrow(UsageError)
    },
  )

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

  it('rejects an unknown suffix', () => {
    // Q and R postdate the gnulib diffutils 3.10 was built against, so
    // they are invalid values rather than overflowing ones: `0Q` fails
    // where `0Z` is a valid zero.
    expect(() => parseCount('1Q', '--bytes')).toThrow(UsageError)
    expect(() => parseCount('0Q', '--bytes')).toThrow(UsageError)
    expect(parseCount('0Z', '--bytes')).toBe(0)
  })

  it('reads the digits at base zero', () => {
    // xstrtoumax's base 0: a bare leading zero is octal and 0x is hex,
    // neither of which BigInt() would read on its own.
    expect(parseCount('010', '--bytes')).toBe(8)
    expect(parseCount('0x400', '--bytes')).toBe(1024)
    expect(parseCount('+1010', '--bytes')).toBe(1010)
    expect(parseCount(' 1', '--bytes')).toBe(1)
    expect(() => parseCount('1 ', '--bytes')).toThrow(UsageError)
    expect(() => parseCount('-1', '--bytes')).toThrow(UsageError)
  })

  it('rejects a product past INTMAX', () => {
    // The ceiling is INTMAX, not UINTMAX, and overflow reports as the
    // same invalid-value error as a bad suffix -- not od's "too large".
    expect(parseCount('7E', '--bytes')).toBe(7 * 1024 ** 6)
    for (const raw of ['9223372036854775808', '8E', '1Z', '1Y']) {
      expect(() => parseCount(raw, '--bytes')).toThrow(UsageError)
    }
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
  it('switches the word to byte under -b', async () => {
    // GNU counts in `byte` under -b and in `char` otherwise.
    const plain = await run(ENC.encode('abc'), ENC.encode('aXc'))
    const tagged = await run(ENC.encode('abc'), ENC.encode('aXc'), { print_bytes: true })
    expect(plain.out).toBe('/F/one /F/two differ: char 2, line 1\n')
    expect(tagged.out).toBe('/F/one /F/two differ: byte 2, line 1 is 142 b 130 X\n')
  })

  it('pads the octal to three columns under -l', async () => {
    const r = await run(bytes(97, 1, 99), bytes(97, 127, 99), { verbose: true })
    expect(r.out).toBe('2   1 177\n')
  })

  it('adds a four-wide char column under -bl', async () => {
    const r = await run(ENC.encode('abc'), ENC.encode('aXc'), { verbose: true, print_bytes: true })
    expect(r.out).toBe('2 142 b    130 X\n')
  })

  it('applies the skip per file', async () => {
    // `-i 0:3` keeps all of the first file and drops three bytes of the
    // second, so the very first compared byte differs.
    const r = await run(ENC.encode('abcdefgh'), ENC.encode('abcXefgh'), { ignore_initial: '0:3' })
    expect(r.out).toBe('/F/one /F/two differ: char 1, line 1\n')
    expect(r.code).toBe(1)
  })

  it('reports EOF on stderr naming the byte and the line', async () => {
    const r = await run(ENC.encode('ab\nc'), ENC.encode('ab\ncdef'))
    expect(r.out).toBe('')
    expect(r.err).toBe('cmp: EOF on /F/one after byte 4, in line 2\n')
    expect(r.code).toBe(1)
  })

  it('drops the line clause from the EOF diagnostic under -l', async () => {
    const r = await run(ENC.encode('aXc'), ENC.encode('aYcdef'), { verbose: true })
    expect(r.out).toBe('2 130 131\n')
    expect(r.err).toBe('cmp: EOF on /F/one after byte 3\n')
    expect(r.code).toBe(1)
  })

  it('reports no difference for a limit inside the common prefix', async () => {
    const r = await run(ENC.encode('abcdef'), ENC.encode('abcXef'), { bytes: '2' })
    expect(r).toEqual({ out: '', err: '', code: 0 })
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
  it('reads a dash operand from stdin and names it dash', async () => {
    const r = await runWithStdin([DASH, P2], 'one\n', 'two\n')
    expect(r).toEqual({ out: '- /F/two differ: char 1, line 1\n', err: '', code: 1 })
  })

  it('reads /dev/stdin from stdin and names it as typed', async () => {
    const r = await runWithStdin([DEV_STDIN, P2], 'one\n', 'two\n')
    expect(r).toEqual({ out: '/dev/stdin /F/two differ: char 1, line 1\n', err: '', code: 1 })
  })

  it('compares a lone operand with stdin', async () => {
    const r = await runWithStdin([P2], 'ab', 'abc')
    expect(r).toEqual({ out: '', err: 'cmp: EOF on - after byte 2, in line 1\n', code: 1 })
  })

  it("refuses no operand with GNU's missing operand usage error", async () => {
    const stream = (p: PathSpec): AsyncIterable<Uint8Array> => {
      throw new Error(`read ${p.virtual}`)
    }
    const call = cmpGeneric([], [], { flags: {}, stdin: null } as unknown as CommandOpts, stream)
    await expect(call).rejects.toThrow(
      new UsageError(
        "cmp: missing operand after 'cmp'\ncmp: Try 'cmp --help' for more information.",
      ),
    )
    await expect(call).rejects.toMatchObject({ exitCode: 2 })
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

  it('names the line an EOF on a line boundary closed', async () => {
    const r = await run(ENC.encode('ab\n'), ENC.encode('ab\ncd'))
    expect(r.err).toBe('cmp: EOF on /F/one after byte 3, line 1\n')
  })

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

  it('sizes -l offsets by the file, not the stream', async () => {
    const r = await runWithStdin([DASH, P2], 'hello\nx\n', 'hello\nworld\nfoo\nbar\nbaz\n', {
      verbose: true,
    })
    expect(r.out).toBe(' 7 170 167\n 8  12 157\n')
    expect(r.err).toBe('cmp: EOF on - after byte 8\n')
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
  it('keeps exit 2 for an operand it cannot read', async () => {
    // diffutils 3.10: `cmp -s a.txt nope` prints nothing and exits 2; the
    // message is what -s drops, not the trouble.
    // eslint-disable-next-line require-yield
    async function* missing(p: PathSpec): AsyncIterable<Uint8Array> {
      await Promise.resolve()
      throw enoent(p)
    }
    for (const [flags, want] of [
      [{ quiet: true }, ''],
      [{}, 'cmp: /F/one: No such file or directory\n'],
    ] as const) {
      const opts = { flags, stdin: null } as unknown as CommandOpts
      const [src, io] = await cmpGeneric([P1, P2], [], opts, missing)
      expect(src).toBeNull()
      expect(DEC.decode(await materialize(io.stderr))).toBe(want)
      expect(io.exitCode).toBe(2)
    }
  })

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

  it('refuses -l with -s', async () => {
    // --verbose is -l and --silent is -s; diffutils refuses the pair while it
    // reads the options.
    const call = run(ENC.encode('a'), ENC.encode('b'), { verbose: true, silent: true })
    await expect(call).rejects.toThrow(
      "cmp: options -l and -s are incompatible\ncmp: Try 'cmp --help' for more information.",
    )
  })
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
    [['x'], "cmp: invalid --ignore-initial value 'x'"],
    [['1', 'y'], "cmp: invalid --ignore-initial value 'y'"],
    [[''], "cmp: invalid --ignore-initial value ''"],
    [['1:2'], "cmp: invalid --ignore-initial value '1:2'"],
    [['1 '], "cmp: invalid --ignore-initial value '1 '"],
    [['9223372036854775808'], "cmp: invalid --ignore-initial value '9223372036854775808'"],
    // Both skips parse before the extra one is refused.
    [['1', '2', '3'], "cmp: extra operand '3'"],
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
