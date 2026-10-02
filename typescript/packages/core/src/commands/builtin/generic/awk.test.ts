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

import { stripSlash } from '../../../utils/slash.ts'
import { describe, expect, it } from 'vitest'
import { IOResult, materialize } from '../../../io/types.ts'
import { PathSpec } from '../../../types.ts'
import type { CommandOpts } from '../../config.ts'
import { awkGeneric } from './awk.ts'

const ENC = new TextEncoder()
const DEC = new TextDecoder()

function spec(path: string): PathSpec {
  return new PathSpec({
    vfsPath: stripSlash(path),
    virtual: path,
    directory: path,
    resolved: true,
  })
}

function opts(
  flags: Record<string, string | boolean | number | string[]> = {},
  stdin: Uint8Array | null = null,
): CommandOpts {
  return { stdin, flags, filetypeFns: null, cwd: '/', vfs: {} } as CommandOpts
}

function makeStream(files: Record<string, string>) {
  return function stream(p: PathSpec): AsyncIterable<Uint8Array> {
    const content = files[p.virtual]
    async function* gen(): AsyncIterable<Uint8Array> {
      await Promise.resolve()
      if (content === undefined) {
        // Stamped like a real backend's ENOENT; awk rethrows anything else.
        const err = new Error(p.virtual) as Error & { code: string }
        err.code = 'ENOENT'
        throw err
      }
      yield ENC.encode(content)
    }
    return gen()
  }
}

async function run(
  paths: PathSpec[],
  texts: string[],
  o: CommandOpts,
  files: Record<string, string> = {},
): Promise<[string, IOResult]> {
  const result = await awkGeneric(paths, texts, o, makeStream(files))
  const [stdout, io] = result ?? [null, new IOResult()]
  return [DEC.decode(await materialize(stdout)), io]
}

describe('awkGeneric', () => {
  it('collapses whitespace with the default FS', async () => {
    const [out] = await run([], ['{print $2}'], opts({}, ENC.encode('a   b\n\tx\t \ty\n')))
    expect(out).toBe('b\ny\n')
  })

  it('collapses whitespace with an explicit single-space FS', async () => {
    const [out] = await run([], ['{print $2}'], opts({ F: ' ' }, ENC.encode('a   b\n')))
    expect(out).toBe('b\n')
  })

  it('splits into characters with an empty FS', async () => {
    const [out] = await run([], ['{print $2}'], opts({ F: '' }, ENC.encode('abc\n')))
    expect(out).toBe('b\n')
  })

  it('processes all files with continuous NR and caches each', async () => {
    const files = { '/a.txt': 'one\ntwo\n', '/b.txt': 'three\n' }
    const [out, io] = await run([spec('/a.txt'), spec('/b.txt')], ['{print NR, $1}'], opts(), files)
    expect(out).toBe('1 one\n2 two\n3 three\n')
    expect(io.cache).toEqual(['/a.txt', '/b.txt'])
  })

  it('keeps lines separate when a file lacks a trailing newline', async () => {
    const files = { '/a.txt': 'one', '/b.txt': 'two\n' }
    const [out] = await run([spec('/a.txt'), spec('/b.txt')], ['{print NR, $1}'], opts(), files)
    expect(out).toBe('1 one\n2 two\n')
  })

  it.each<[string | string[], Record<string, string>, string[], string]>([
    [
      '/prog.awk',
      { '/prog.awk': '{print $1}\n', '/data.txt': 'alpha beta\n' },
      ['/data.txt'],
      'alpha\n',
    ],
    [
      '/prog.awk',
      { '/prog.awk': '{print NR, $1}\n', '/a.txt': 'one\n', '/b.txt': 'two\n' },
      ['/a.txt', '/b.txt'],
      '1 one\n2 two\n',
    ],
    [
      ['/p1.awk', '/p2.awk'],
      { '/p1.awk': '{sum += $1}\n', '/p2.awk': 'END {print sum}\n', '/nums.txt': '1\n2\n3\n' },
      ['/nums.txt'],
      '6\n',
    ],
  ])('runs the -f program %j over the data paths', async (f, files, data, expected) => {
    const [out, io] = await run(data.map(spec), [], opts({ f }), files)
    expect(out).toBe(expected)
    expect(io.cache).toEqual(data)
  })

  it('emits blank lines for print of an empty string', async () => {
    const [out] = await run([], ['{print ""}'], opts({}, ENC.encode('one\ntwo\n')))
    expect(out).toBe('\n\n')
  })

  it('prints a literal closing brace', async () => {
    const [out] = await run([], ['{print "}"}'], opts({}, ENC.encode('line\n')))
    expect(out).toBe('}\n')
  })

  it('returns exit 2 when the -f program file is unreadable', async () => {
    const result = await awkGeneric(
      [spec('/data.txt')],
      [],
      opts({ f: '/missing.awk' }),
      makeStream({ '/data.txt': 'x\n' }),
    )
    const [stdout, io] = result ?? [null, new IOResult()]
    expect(stdout).toBeNull()
    expect(io.exitCode).toBe(2)
    expect(DEC.decode(await materialize(io.stderr))).toBe(
      'awk: /missing.awk: No such file or directory\n',
    )
  })

  it('propagates a -f read failure that is not absence', async () => {
    const raw = new Error('S3 GET prog.awk failed: 403 Forbidden')
    function stream(): AsyncIterable<Uint8Array> {
      throw raw
    }
    await expect(
      awkGeneric([spec('/data.txt')], [], opts({ f: '/prog.awk' }), stream),
    ).rejects.toThrow('403 Forbidden')
  })

  it('resolves a relative -f program file against the cwd', async () => {
    const files = { '/data/prog.awk': '{print $1}\n', '/data/in.txt': 'hey there\n' }
    const o = { ...opts({ f: 'prog.awk' }), cwd: '/data' } as CommandOpts
    const result = await awkGeneric([spec('/data/in.txt')], [], o, makeStream(files))
    const [stdout] = result ?? [null, new IOResult()]
    expect(DEC.decode(await materialize(stdout))).toBe('hey\n')
  })

  it('lets the last duplicate -v assignment win', async () => {
    const [out] = await run(
      [],
      ['{print x}'],
      opts({ v: ['x=first', 'x=second'] }, ENC.encode('line\n')),
    )
    expect(out).toBe('second\n')
  })

  it('emits a blank line for a bare print in BEGIN', async () => {
    const [out] = await run([], ['BEGIN {print} {print $1}'], opts({}, ENC.encode('a\n')))
    expect(out).toBe('\na\n')
  })

  it('prints a literal closing brace behind a condition', async () => {
    const [out] = await run([], ['/x/ {print "}"}'], opts({}, ENC.encode('x\ny\n')))
    expect(out).toBe('}\n')
  })

  it('assigns from a field', async () => {
    const [out] = await run([], ['{x = $2; print x}'], opts({}, ENC.encode('a b\n')))
    expect(out).toBe('b\n')
  })

  it('prints empty for an out-of-range field', async () => {
    const [out] = await run([], ['{print $5}'], opts({}, ENC.encode('one two\n')))
    expect(out).toBe('\n')
  })
})

describe('awk runs what the scraper refused', () => {
  it.each([
    ['{x = y + 1; print x}', 'line\n', '1\n'],
    ['{print toupper($1)}', 'line\n', 'LINE\n'],
    ['{printf "%s\\n", $1}', 'line\n', 'line\n'],
    ['{if ($1) print $1}', 'line\n', 'line\n'],
    ['length($1) ~ /1/', 'a\n', 'a\n'],
    ['NR % 2 == 0 {print}', 'a\nb\n', 'b\n'],
    ['{gsub(/a/, "b"); print}', 'banana\n', 'bbnbnb\n'],
    ['{while (i++ < 2) print i, $1}', 'x\n', '1 x\n2 x\n'],
    ['{c[$1]++} END{print c["a"], length(c)}', 'a\nb\na\n', '2 2\n'],
    ['function twice(n){return n*2} {print twice($1)}', '21\n', '42\n'],
  ])('runs %j', async (program, stdin, expected) => {
    const [out] = await run([], [program], opts({}, ENC.encode(stdin)))
    expect(out).toBe(expected)
  })
})

async function runIo(program: string, stdin: string): Promise<[string, number, string]> {
  const [out, io] = await run([], [program], opts({}, ENC.encode(stdin)))
  return [out, io.exitCode, DEC.decode(await materialize(io.stderr))]
}

describe('awk fatal paths', () => {
  it.each([
    ['{print > "out.txt"}', 'awk: file output requires a workspace\n'],
    ['{system("ls")}', 'awk: running a command requires a workspace\n'],
    ['{"ls" | getline}', 'awk: running a command requires a workspace\n'],
    ['{print | "cat"}', 'awk: running a command requires a workspace\n'],
  ])('refuses %j', async (program, message) => {
    expect(await runIo(program, 'a\n')).toEqual(['', 2, message])
  })
})

async function runStdin(
  program: string,
  stdin: string,
  flags: Record<string, string | boolean | number | string[]> = {},
): Promise<string> {
  const [out] = await run([], [program], opts(flags, ENC.encode(stdin)))
  return out
}

describe('awk regex match', () => {
  it('matches a bare regex pattern holding an operator', async () => {
    expect(await runStdin('/A&&B/', 'xA&&By\nAB\n')).toBe('xA&&By\n')
  })

  it('matches a numeric right-hand side as text', async () => {
    expect(await runStdin('$1 ~ 1', '12\n3\n')).toBe('12\n')
  })

  it('accepts $NF and a builtin on the left', async () => {
    expect(await runStdin('$NF ~ /^App/', 'x y Application\nx y Other\n')).toBe('x y Application\n')
    expect(await runStdin('NR ~ /[13]/', 'a\nb\nc\n')).toBe('a\nc\n')
  })

  it('keeps a comparison operator inside the regex', async () => {
    expect(await runStdin('$0 ~ /a<b/', 'a<b\nab\n')).toBe('a<b\n')
    expect(await runStdin('$0 ~ /a==b/', 'a==b\nab\n')).toBe('a==b\n')
  })

  it('keeps a comparison operator inside a bare regex', async () => {
    expect(await runStdin('/a<b/', 'a<b\nab\n')).toBe('a<b\n')
  })

  it('keeps an escaped slash inside the regex', async () => {
    expect(await runStdin('$1 ~ /a\\/b/', 'a/b\nab\n')).toBe('a/b\n')
  })

  it('does not read an interval brace as the action brace', async () => {
    expect(await runStdin('$1 ~ /a{2}/ {print $2}', 'aa 1\na 2\n')).toBe('1\n')
  })

  it('needs no spaces around the operator', async () => {
    expect(await runStdin('$1~/a/', 'a b\nc d\n')).toBe('a b\n')
  })

  it('negates an operand by its truthiness', async () => {
    expect(await runStdin('!$1', '0\n1\nfoo\n\n')).toBe('0\n\n')
    expect(await runStdin('!x', 'a\nb\n', { v: 'x=0' })).toBe('a\nb\n')
  })
})

describe('awk compound statements', () => {
  const INPUT = ENC.encode('Welcome to x\nInstall it\n')

  it.each([
    ['{{print $1}}', 'Welcome\nInstall\n'],
    ['{{{print $1}}}', 'Welcome\nInstall\n'],
    ['{{print $1}; print $2}', 'Welcome\nto\nInstall\nit\n'],
    ['{print $1;{print $2}}', 'Welcome\nto\nInstall\nit\n'],
  ])('runs the body of %s', async (program, expected) => {
    const [out] = await run([], [program], opts({}, INPUT))
    expect(out).toBe(expected)
  })

  it('does not split on a semicolon inside a string', async () => {
    const [out] = await run([], ['{print "a;b", $1}'], opts({}, ENC.encode('x\n')))
    expect(out).toBe('a;b x\n')
  })
})

async function* chunked(parts: readonly (string | Uint8Array)[]): AsyncIterable<Uint8Array> {
  for (const part of parts) {
    await Promise.resolve()
    yield typeof part === 'string' ? ENC.encode(part) : part
  }
}

describe('awk RS', () => {
  it.each<[(string | Uint8Array)[], string, string]>([
    [['a\n', '\nb\n'], '', 'a|b|'],
    [['a1', '2b'], '[0-9]+', 'a|b|'],
    [['a:', 'b'], ':', 'a|b|'],
    [[Uint8Array.of(0x68, 0xc3), Uint8Array.of(0xa9, 0x3a, 0x78)], ':', 'h\u00e9|x|'],
  ])('holds a record across the chunks %j', async (parts, rs, expected) => {
    const o = { ...opts({ v: [`RS=${rs}`] }), stdin: chunked(parts) }
    const [out] = await run([], ['{printf "%s|", $0}'], o)
    expect(out).toBe(expected)
  })

  it('never lets a record span two files', async () => {
    const files = { '/a.txt': 'a:b', '/b.txt': 'c:d:' }
    const paths = [spec('/a.txt'), spec('/b.txt')]
    const [out] = await run(paths, ['{print FNR, NR, $0}'], opts({ v: ['RS=:'] }), files)
    expect(out).toBe('1 1 a\n2 2 b\n1 3 c\n2 4 d\n')
  })

  it('takes the whole newline run as the paragraph separator', async () => {
    const o = { ...opts({ v: ['RS='] }), stdin: chunked(['a\n\n', '\nb\n']) }
    const [out] = await run([], ['{printf "%s|", $0; RS="\\n"}'], o)
    expect(out).toBe('a|b|')
  })
})
