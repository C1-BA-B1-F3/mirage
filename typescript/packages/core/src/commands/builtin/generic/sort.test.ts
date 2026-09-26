import { parseCommand, parseToKwargs } from '../../spec/parser.ts'
import { specOf } from '../../spec/builtins.ts'
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

import { materialize } from '../../../io/types.ts'
import { PathSpec } from '../../../types.ts'
import { unreadableStdin } from '../../../shell/descriptors.ts'
import { eisdir, enoent } from '../../../utils/errors.ts'
import type { CommandOpts } from '../../config.ts'
import { parseFlags, sortGeneric } from './sort.ts'

const DEC = new TextDecoder()

async function stderrOf(flags: CommandOpts['flags']): Promise<[string, number]> {
  const opts = {
    stdin: new TextEncoder().encode('b\na\n'),
    flags,
    filetypeFns: null,
    cwd: '/',
    vfs: { kind: 'ram' } as never,
  } as CommandOpts
  const result = await sortGeneric([], opts, () => {
    throw new Error('paths are empty; the source is stdin')
  })
  if (result === null) throw new Error('sort returned no result')
  const io = result[1]
  // stderr is null on a run that was not refused, which the prefix cases
  // below are.
  return [DEC.decode((io.stderr ?? new Uint8Array()) as Uint8Array), io.exitCode]
}

// GNU's ARGMATCH refusal names the refused word through gnulib's quote(),
// so a byte outside 0x20-0x7e comes back escaped rather than interpolated
// raw. Every row measured against GNU coreutils 9.4 under `LC_ALL=C` with a
// raw `bytes` argv (`sort --check=<w>`). Mirrors test_sort.py.
describe('sort quotes the word --check refuses', () => {
  it.each([
    ['xé', 'x\\303\\251'],
    ['x\r', 'x\\r'],
    ['x\x01', 'x\\001'],
    ['x\x7f', 'x\\177'],
    ["x'", "x\\'"],
    ['x\\', 'x\\\\'],
  ])('escapes %j in the --check clause', async (value, escaped) => {
    const [stderr] = await stderrOf({ check: value })
    expect(stderr.split('\n')[0]).toBe(`sort: invalid argument '${escaped}' for '--check'`)
  })
})

// Measured, coreutils 9.4: `sort --check=x f` is SIX lines and exit 1.
// `quiet` and `silent` are aliases of one value, so gnulib's
// `argmatch_valid` puts them on one row; the exit is 1, not sort's usual
// usage code of 2, because `argmatch_die` always calls
// `usage (EXIT_FAILURE)`. Mirrors test_sort.py.
describe('sort --check refusal carries GNU candidate block', () => {
  it('lists the candidates and exits 1', async () => {
    const [stderr, code] = await stderrOf({ check: 'x' })
    expect(stderr).toBe(
      "sort: invalid argument 'x' for '--check'\n" +
        "Valid arguments are:\n  - 'quiet', 'silent'\n  - 'diagnose-first'\n" +
        "Try 'sort --help' for more information.\n",
    )
    expect(code).toBe(1)
  })

  it('words an empty value as ambiguous', async () => {
    const [stderr, code] = await stderrOf({ check: '' })
    expect(stderr.split('\n')[0]).toBe("sort: ambiguous argument '' for '--check'")
    expect(code).toBe(1)
  })

  // `sort --check=q`, `=s` and `=d` all exit 0 on sorted input (measured,
  // coreutils 9.4). The stdin here is NOT sorted, so the canonical word is
  // observable: the ('quiet', 'silent') value stays silent while
  // diagnose-first names the first disorder. Mirrors test_sort.py.
  it.each(['q', 's', 'quiet', 'silent'])(
    'resolves --check=%s to the quiet value',
    async (value) => {
      const [stderr, code] = await stderrOf({ check: value })
      expect(stderr).toBe('')
      expect(code).toBe(1)
    },
  )

  it.each(['d', 'diagnose', 'diagnose-first'])(
    'resolves --check=%s to diagnose-first',
    async (value) => {
      const [stderr, code] = await stderrOf({ check: value })
      expect(stderr).toContain('disorder')
      expect(code).toBe(1)
    },
  )

  it('still refuses a word no candidate starts with', async () => {
    const [stderr] = await stderrOf({ check: 'qu1et' })
    expect(stderr.split('\n')[0]).toBe("sort: invalid argument 'qu1et' for '--check'")
  })
})

type Source = Uint8Array | Error

function spec(virtual: string, rawPath?: string): PathSpec {
  return new PathSpec({
    virtual,
    directory: virtual.slice(0, virtual.lastIndexOf('/') + 1),
    vfsPath: virtual,
    ...(rawPath === undefined ? {} : { rawPath }),
  })
}

function bytes(text: string): Uint8Array {
  return new TextEncoder().encode(text)
}

interface Run {
  paths?: PathSpec[]
  files?: Record<string, Source>
  flags?: CommandOpts['flags']
  stdin?: CommandOpts['stdin']
  write?: (path: PathSpec, data: Uint8Array) => Promise<void>
}

async function run(r: Run): Promise<[string, string, number]> {
  const opts = {
    stdin: r.stdin ?? null,
    flags: r.flags ?? {},
    filetypeFns: null,
    cwd: '/',
    vfs: { kind: 'ram' } as never,
  } as CommandOpts
  const files = r.files ?? {}
  async function* stream(path: PathSpec): AsyncIterable<Uint8Array> {
    await Promise.resolve()
    const source = files[path.virtual]
    if (source === undefined) throw new Error(`unexpected read of ${path.virtual}`)
    if (source instanceof Error) throw source
    yield source
  }
  const result = await sortGeneric(r.paths ?? [], opts, stream, r.write)
  if (result === null) throw new Error('sort returned no result')
  const [out, io] = result
  const stdout = out === null ? '' : DEC.decode(await materialize(out))
  const stderr = io.stderr === null ? '' : DEC.decode(await materialize(io.stderr))
  return [stdout, stderr, io.exitCode]
}

// Every expectation below was measured against GNU coreutils 9.7 on
// debian:stable-slim under LC_ALL=C. Mirrors test_sort.py.
describe('sort names the step an input failed at', () => {
  it('words a missing input as cannot read, exit 2', async () => {
    const [, stderr, code] = await run({
      paths: [spec('/data/missing.txt')],
      files: { '/data/missing.txt': enoent('/data/missing.txt') },
    })
    expect(stderr).toBe('sort: cannot read: /data/missing.txt: No such file or directory\n')
    expect(code).toBe(2)
  })

  it('names the input as typed, quoted when it needs it', async () => {
    const [, stderr] = await run({
      paths: [spec('/data/no such.txt', 'no such.txt')],
      files: { '/data/no such.txt': enoent('/data/no such.txt') },
    })
    expect(stderr).toBe("sort: cannot read: 'no such.txt': No such file or directory\n")
  })

  it('reads a directory as read failed, behind a missing input', async () => {
    const files = {
      '/data/dir': eisdir('/data/dir'),
      '/data/missing.txt': enoent('/data/missing.txt'),
    }
    const [, alone, code] = await run({ paths: [spec('/data/dir')], files })
    expect(alone).toBe('sort: read failed: /data/dir: Is a directory\n')
    expect(code).toBe(2)
    const [, both] = await run({ paths: [spec('/data/dir'), spec('/data/missing.txt')], files })
    expect(both).toBe('sort: cannot read: /data/missing.txt: No such file or directory\n')
  })

  it('stops at the first input that fails its access check', async () => {
    const [, stderr] = await run({
      paths: [spec('/data/m1'), spec('/data/m2')],
      files: { '/data/m1': enoent('/data/m1') },
    })
    expect(stderr).toBe('sort: cannot read: /data/m1: No such file or directory\n')
  })

  it.each([
    [{}, 'stat failed'],
    [{ merge: true }, 'read failed'],
    [{ c: true }, 'read failed'],
  ])('fails a closed stdin where GNU first touches it (%j)', async (flags, verb) => {
    const [, stderr, code] = await run({ flags, stdin: unreadableStdin() })
    expect(stderr).toBe(`sort: ${verb}: -: Bad file descriptor\n`)
    expect(code).toBe(2)
  })

  it('opens the input -c reads rather than testing access', async () => {
    const [, stderr, code] = await run({
      paths: [spec('/data/missing.txt')],
      files: { '/data/missing.txt': enoent('/data/missing.txt') },
      flags: { C: true },
    })
    expect(stderr).toBe('sort: open failed: /data/missing.txt: No such file or directory\n')
    expect(code).toBe(2)
  })

  it.each([
    [enoent('/data/nodir/out.txt'), 'No such file or directory'],
    [eisdir('/data/nodir/out.txt'), 'Is a directory'],
  ])('words an output that will not open as open failed', async (failure, strerror) => {
    const [, stderr, code] = await run({
      stdin: bytes('b\na\n'),
      flags: { output: ['/data/nodir/out.txt'] },
      write: () => Promise.reject(failure),
    })
    expect(stderr).toBe(`sort: open failed: /data/nodir/out.txt: ${strerror}\n`)
    expect(code).toBe(2)
  })
})

describe('sort -c and -C', () => {
  it.each([
    [{ c: true }, 'c'],
    [{ C: true }, 'C'],
    [{ check: true }, 'c'],
    [{ check: 'quiet' }, 'C'],
    [{ check: 'silent' }, 'C'],
    [{ check: 'diagnose-first' }, 'c'],
  ])('refuses an output by the mode letter (%j)', async (flags, mode) => {
    const [, stderr, code] = await run({
      stdin: bytes('b\na\n'),
      flags: { ...flags, output: ['/data/out.txt'] },
    })
    expect(stderr).toBe(`sort: options '-${mode}o' are incompatible\n`)
    expect(code).toBe(2)
  })

  it('lets a second operand outrank the output and names the mode', async () => {
    const [, stderr, code] = await run({
      paths: [spec('/data/a'), spec('/data/b')],
      flags: { C: true, output: ['/data/out.txt'] },
    })
    expect(stderr).toBe("sort: extra operand '/data/b' not allowed with -C\n")
    expect(code).toBe(2)
  })

  it('checks quietly under -C and exits 1', async () => {
    const [, stderr, code] = await run({ stdin: bytes('b\na\n'), flags: { C: true } })
    expect(stderr).toBe('')
    expect(code).toBe(1)
  })

  it.each([
    { c: true, C: true },
    { C: true, c: true },
    { c: true, check: 'quiet' },
    { check: 'silent', c: true },
    { C: true, check: true },
  ])('refuses to mix the two modes (%j)', async (flags) => {
    const [, stderr, code] = await run({ stdin: bytes('a\n'), flags })
    expect(stderr).toBe("sort: options '-cC' are incompatible\n")
    expect(code).toBe(2)
  })

  it('accepts one mode asked for twice', () => {
    expect(parseFlags({ C: true, check: 'quiet' }).checkQuiet).toBe(true)
    expect(parseFlags({ c: true, check: 'diagnose-first' }).check).toBe(true)
  })
})

describe('sort -o', () => {
  it('refuses two outputs unless they name one file', async () => {
    const [, stderr, code] = await run({
      stdin: bytes('a\n'),
      flags: { output: ['/data/p1', '/data/p2'] },
    })
    expect(stderr).toBe('sort: multiple output files specified\n')
    expect(code).toBe(2)
    expect(parseFlags({ output: ['/data/p1', '/data/p1'] }).output?.virtual).toBe('/data/p1')
  })

  it('refuses the first bad option on the line', async () => {
    const [, first] = await run({
      stdin: bytes('a\n'),
      flags: { output: ['/p1', '/p2'], key: ['0'] },
    })
    expect(first).toBe('sort: multiple output files specified\n')
    const [, key] = await run({
      stdin: bytes('a\n'),
      flags: { key: ['0'], output: ['/p1', '/p2'] },
    })
    expect(key).toContain('invalid field specification')
    const [, modes] = await run({
      stdin: bytes('a\n'),
      flags: { c: true, C: true, output: ['/p1', '/p2'] },
    })
    expect(modes).toBe("sort: options '-cC' are incompatible\n")
  })
})

// GNU checks the orderings after its option loop and before -c's operand
// checks and any input. Measured against GNU coreutils 9.7 under LC_ALL=C.
// Mirrors test_sort.py.
describe('sort refuses incompatible orderings where GNU does', () => {
  const MIXED = { numeric_sort: true, general_numeric_sort: true }

  it.each([
    [{ key: ['0'] }, "sort: field number is zero: invalid field specification '0'\n"],
    [{ output: ['/data/p1', '/data/p2'] }, 'sort: multiple output files specified\n'],
    [{ c: true, C: true }, "sort: options '-cC' are incompatible\n"],
  ])('lets the option loop outrank them (%j)', async (flags, refusal) => {
    const [, stderr, code] = await run({ stdin: bytes('a\n'), flags: { ...MIXED, ...flags } })
    expect(stderr).toBe(refusal)
    expect(code).toBe(2)
  })

  it.each([
    [['/data/a', '/data/b'], { c: true }],
    [['/data/a'], { c: true, output: ['/data/out'] }],
    [['/data/missing'], {}],
  ])('outranks the operands %j', async (paths, flags) => {
    const [, stderr, code] = await run({
      paths: paths.map((path) => spec(path)),
      files: { '/data/missing': enoent('/data/missing') },
      flags: { ...MIXED, ...flags },
    })
    expect(stderr).toBe("sort: options '-gn' are incompatible\n")
    expect(code).toBe(2)
  })
})

describe('sort inputs', () => {
  it('ends each input at its own last line', async () => {
    const [stdout, , code] = await run({
      paths: [spec('/data/f1'), spec('/data/f2')],
      files: { '/data/f1': bytes('b'), '/data/f2': bytes('a\n') },
    })
    expect(stdout).toBe('a\nb\n')
    expect(code).toBe(0)
  })

  it('merges without reordering a run under -m', async () => {
    const [single] = await run({
      paths: [spec('/data/in.txt')],
      files: { '/data/in.txt': bytes('b\na\n') },
      flags: { merge: true },
    })
    expect(single).toBe('b\na\n')
    const [two] = await run({
      paths: [spec('/data/s1'), spec('/data/s2')],
      files: { '/data/s1': bytes('c\na\n'), '/data/s2': bytes('b\n') },
      flags: { merge: true },
    })
    expect(two).toBe('b\nc\na\n')
  })
})

it.each([
  [['-o', 'out', '-k', '2,2', '-k', '0', '-o', 'out2'], 'field number is zero'],
  [['-k', '2,2', '-o', 'out', '-o', 'out2', '-k', '0'], 'multiple output files'],
  [['--check', '--check=quiet'], "options '-cC' are incompatible"],
] as const)('refuses interleaved options in scan order: %j', (argv, message) => {
  const flags = parseToKwargs(parseCommand(specOf('sort'), [...argv], '/data', 'sort'))
  expect(() => parseFlags(flags)).toThrow(message)
})
