import { describe, expect, it } from 'vitest'
import { yieldBytes } from '../../../io/stream.ts'
import { materialize, type ByteSource } from '../../../io/types.ts'
import { FileStat, FileType, PathSpec } from '../../../types.ts'
import { gzip } from '../../../utils/compress.ts'
import { eisdir, enoent } from '../../../utils/errors.ts'
import { decompressInputs, gzipSuffix, suffixRefusal } from './decompress.ts'

const enc = new TextEncoder()
const dec = new TextDecoder()
const HELLO = await gzip(enc.encode('hello'))

function cat(...parts: Uint8Array[]): Uint8Array {
  return new Uint8Array(parts.flatMap((p) => [...p]))
}

function backend(files: Map<string, Uint8Array>) {
  const reads: string[] = []
  async function* read(path: PathSpec): AsyncIterable<Uint8Array> {
    await Promise.resolve()
    reads.push(path.virtual)
    if (path.virtual.endsWith('/dir')) throw eisdir(path)
    const data = files.get(path.virtual)
    if (data === undefined) throw enoent(path)
    yield* yieldBytes(data)
  }
  return {
    reads,
    read,
    options: {
      write: (path: PathSpec, data: Uint8Array) => {
        files.set(path.virtual, data)
        return Promise.resolve()
      },
      unlink: (path: PathSpec) => {
        files.delete(path.virtual)
        return Promise.resolve()
      },
      stat: (path: PathSpec) => {
        if (!files.has(path.virtual)) return Promise.reject(enoent(path))
        return Promise.resolve(new FileStat({ name: path.virtual, type: FileType.FILE }))
      },
    },
  }
}

function typed(virtual: string, rawPath: string): PathSpec {
  return new PathSpec({
    virtual,
    directory: virtual.slice(0, virtual.lastIndexOf('/') + 1),
    vfsPath: virtual.replace(/^\/+/, ''),
    rawPath,
  })
}

// A buffered run's stderr is whole bytes by the time it is read.
function text(bytes: ByteSource | null): string | null {
  return bytes === null ? null : dec.decode(bytes as Uint8Array)
}

it.each([null, 'x', '\x1f'])('stops after fatal input: %j', async (suffix) => {
  const reads: string[] = []
  async function* read(path: PathSpec): AsyncIterable<Uint8Array> {
    await Promise.resolve()
    reads.push(path.virtual)
    yield suffix === null ? new Uint8Array() : cat(HELLO, enc.encode(suffix))
  }
  async function* stdin(): AsyncIterable<Uint8Array> {
    reads.push('stdin')
    yield await gzip(enc.encode('hello'))
  }
  const paths = ['/a/bad.gz', '/b/missing.gz', '-'].map((p) => PathSpec.fromStrPath(p))
  const [body, io] = await decompressInputs(paths, read, { stdin: stdin(), toStdout: true })
  expect(await materialize(body)).toEqual(enc.encode(suffix === null ? '' : 'hello'))
  expect(reads).toEqual(['/a/bad.gz'])
  expect(io.exitCode).toBe(1)
  expect(text(io.stderr)).toBe('\ngzip: /a/bad.gz: unexpected end of file\n')
})

it('retains in-place output on a trailing warning and continues', async () => {
  const files = new Map([
    ['/data/a.gz', cat(HELLO, enc.encode('junk'))],
    ['/data/b.gz', await gzip(enc.encode('w'))],
  ])
  const { read, options } = backend(files)
  const paths = [...files.keys()].map((p) => PathSpec.fromStrPath(p))
  const [body, io] = await decompressInputs(paths, read, { stdin: null, ...options })
  expect(body).toBeNull()
  expect(Object.fromEntries(files)).toEqual({
    '/data/a': enc.encode('hello'),
    '/data/b': enc.encode('w'),
  })
  expect(io.exitCode).toBe(2)
  expect(text(io.stderr)).toBe('\ngzip: /data/a.gz: decompression OK, trailing garbage ignored\n')
})

describe('the names gzip opens', () => {
  // gzip 1.13 opens the name, then the name with each suffix, and names the
  // -S one when every open misses.
  it.each([
    ['.gz', ['/d/x', '/d/x.gz', '/d/x.z', '/d/x-z', '/d/x.Z'], 'x.gz'],
    ['.y', ['/d/x', '/d/x.y', '/d/x.gz', '/d/x.z', '/d/x-z', '/d/x.Z'], 'x.y'],
  ])('retries a missing name with each suffix under -S %s', async (suffix, tried, shown) => {
    const { reads, read, options } = backend(new Map())
    const [body, io] = await decompressInputs([typed('/d/x', 'x')], read, {
      stdin: null,
      toStdout: true,
      suffix,
      ...options,
    })
    expect(await materialize(body)).toEqual(new Uint8Array())
    expect(reads).toEqual(tried)
    expect([io.exitCode, text(io.stderr)]).toEqual([
      1,
      `gzip: ${shown}: No such file or directory\n`,
    ])
  })

  it('takes a retried name as the input and names the output from it', async () => {
    const files = new Map([['/d/x.z', HELLO]])
    const { read, options } = backend(files)
    const [, io] = await decompressInputs([typed('/d/x', 'x')], read, { stdin: null, ...options })
    expect([io.exitCode, Object.fromEntries(files)]).toEqual([0, { '/d/x': enc.encode('hello') }])
  })

  it('does not retry a name with a known suffix', async () => {
    const { reads, read, options } = backend(new Map())
    const [, io] = await decompressInputs([typed('/d/x.GZ', 'x.GZ')], read, {
      stdin: null,
      ...options,
    })
    expect(reads).toEqual(['/d/x.GZ'])
    expect(text(io.stderr)).toBe('gzip: x.GZ: No such file or directory\n')
  })

  it('tries the suffixes themselves for the empty name', async () => {
    const reads: string[] = []
    // eslint-disable-next-line require-yield
    async function* read(path: PathSpec): AsyncIterable<Uint8Array> {
      await Promise.resolve()
      reads.push(path.rawPath)
      throw enoent(path)
    }
    const empty = new PathSpec({
      virtual: '/d',
      directory: '/',
      vfsPath: 'd',
      rawPath: '',
      walkError: 'ENOENT',
    })
    const [, io] = await decompressInputs([empty], read, {
      stdin: null,
      ...backend(new Map()).options,
    })
    expect(reads).toEqual(['', '.gz', '.z', '-z', '.Z'])
    expect(text(io.stderr)).toBe('gzip: .gz: No such file or directory\n')
  })
})

describe('in place', () => {
  it.each([
    [false, 'gzip: /d/a.txt: unknown suffix -- ignored\n', 2],
    [true, null, 0],
  ] as const)('skips a name without a known suffix (quiet %s)', async (quiet, stderr, code) => {
    const files = new Map([['/d/a.txt', HELLO]])
    const { read, options } = backend(files)
    const [, io] = await decompressInputs([PathSpec.fromStrPath('/d/a.txt')], read, {
      stdin: null,
      quiet,
      ...options,
    })
    expect([text(io.stderr), io.exitCode]).toEqual([stderr, code])
    expect(Object.fromEntries(files)).toEqual({ '/d/a.txt': HELLO })
  })

  it('decompresses .tgz and .taz, in any case, to .tar', async () => {
    const files = new Map([
      ['/d/a.TGZ', HELLO],
      ['/d/b.taz', HELLO],
    ])
    const { read, options } = backend(files)
    const paths = ['/d/a.TGZ', '/d/b.taz'].map((p) => PathSpec.fromStrPath(p))
    await decompressInputs(paths, read, { stdin: null, ...options })
    expect(Object.fromEntries(files)).toEqual({
      '/d/a.tar': enc.encode('hello'),
      '/d/b.tar': enc.encode('hello'),
    })
  })

  it.each([
    [false, 2, { '/d/e.gz': HELLO, '/d/e': enc.encode('old') }],
    [true, 0, { '/d/e': enc.encode('hello') }],
  ] as const)('needs -f (%s) to replace an output already there', async (force, code, after) => {
    const files = new Map([
      ['/d/e.gz', HELLO],
      ['/d/e', enc.encode('old')],
    ])
    const { read, options } = backend(files)
    const [, io] = await decompressInputs([PathSpec.fromStrPath('/d/e.gz')], read, {
      stdin: null,
      force,
      ...options,
    })
    expect([io.exitCode, Object.fromEntries(files)]).toEqual([code, after])
    if (!force) expect(text(io.stderr)).toBe('gzip: /d/e already exists;\tnot overwritten\n')
  })

  it('names an output already there ahead of a corrupt body', async () => {
    // gzip checks the output once the header reads, before the body.
    const files = new Map([
      ['/d/e.gz', HELLO.subarray(0, -3)],
      ['/d/e', enc.encode('old')],
    ])
    const { read, options } = backend(files)
    const [, io] = await decompressInputs([PathSpec.fromStrPath('/d/e.gz')], read, {
      stdin: null,
      ...options,
    })
    expect([io.exitCode, text(io.stderr)]).toEqual([
      2,
      'gzip: /d/e already exists;\tnot overwritten\n',
    ])
  })

  it('names a bad header ahead of an output already there', async () => {
    const files = new Map([
      ['/d/e.gz', enc.encode('plain\n')],
      ['/d/e', enc.encode('old')],
    ])
    const { read, options } = backend(files)
    const [, io] = await decompressInputs([PathSpec.fromStrPath('/d/e.gz')], read, {
      stdin: null,
      ...options,
    })
    expect([io.exitCode, text(io.stderr)]).toEqual([1, '\ngzip: /d/e.gz: not in gzip format\n'])
  })
})

describe('to stdout', () => {
  it.each([
    [false, 'gzip: /d/dir is a directory -- ignored\n'],
    [true, null],
  ] as const)('warns of a directory, silent under quiet %s', async (quiet, stderr) => {
    const { read, options } = backend(new Map())
    const [body, io] = await decompressInputs([PathSpec.fromStrPath('/d/dir')], read, {
      stdin: null,
      toStdout: true,
      quiet,
      ...options,
    })
    expect(await materialize(body)).toEqual(new Uint8Array())
    expect([text(io.stderr), io.exitCode]).toEqual([stderr, 2])
  })

  it.each([
    ['plain', enc.encode('plain\n'), 'plain\n'],
    ['empty', new Uint8Array(), ''],
    ['one byte', enc.encode('\x1f'), '\x1f'],
    ['trailing bytes', cat(HELLO, enc.encode('junk')), 'hellojunk'],
    ['trailing zeros', cat(HELLO, new Uint8Array(2)), 'hello\0\0'],
  ])('copies what is not gzip under -f: %s', async (_name, data, out) => {
    const { read, options } = backend(new Map([['/d/f', data]]))
    const [body, io] = await decompressInputs([PathSpec.fromStrPath('/d/f')], read, {
      stdin: null,
      toStdout: true,
      force: true,
      ...options,
    })
    expect([dec.decode(await materialize(body)), io.exitCode, text(io.stderr)]).toEqual([
      out,
      0,
      null,
    ])
  })

  it('ends the run at stdin that is not gzip', async () => {
    const { reads, read, options } = backend(new Map([['/d/x.gz', HELLO]]))
    async function* stdin(): AsyncIterable<Uint8Array> {
      await Promise.resolve()
      yield enc.encode('plain')
    }
    const paths = ['-', '/d/x.gz'].map((p) => PathSpec.fromStrPath(p))
    const [body, io] = await decompressInputs(paths, read, {
      stdin: stdin(),
      toStdout: true,
      ...options,
    })
    expect(await materialize(body)).toEqual(new Uint8Array())
    expect(reads).toEqual([])
    expect([io.exitCode, text(io.stderr)]).toEqual([1, '\ngzip: stdin: not in gzip format\n'])
  })

  it('keeps the trailing garbage exit code under quiet', async () => {
    const { read, options } = backend(new Map([['/d/f.gz', cat(HELLO, enc.encode('junk'))]]))
    const [body, io] = await decompressInputs([PathSpec.fromStrPath('/d/f.gz')], read, {
      stdin: null,
      toStdout: true,
      quiet: true,
      ...options,
    })
    expect([dec.decode(await materialize(body)), io.exitCode, text(io.stderr)]).toEqual([
      'hello',
      2,
      null,
    ])
  })
})

it.each(['', '.' + 'a'.repeat(30)])('refuses the -S suffix %j before any input', async (suffix) => {
  const { reads, read, options } = backend(new Map([['/d/x.gz', HELLO]]))
  const [, io] = await decompressInputs([PathSpec.fromStrPath('/d/x.gz')], read, {
    stdin: null,
    suffix,
    ...options,
  })
  expect(reads).toEqual([])
  expect([io.exitCode, text(io.stderr)]).toEqual([1, `gzip: invalid suffix '${suffix}'\n`])
})

it.each([
  ['a.gz', '.gz', '.gz'],
  ['a.GZ', '.gz', '.GZ'],
  ['a.Tgz', '.gz', '.Tgz'],
  ['a_z', '.gz', '_z'],
  ['a-GZ', '.gz', '-GZ'],
  ['a.txt', '.gz', null],
  ['.gz', '.gz', null],
  ['d/.gz', '.gz', null],
  ['a.xy', '.XY', '.xy'],
  ['a.gz', 'z', '.gz'],
  ['az', 'z', 'z'],
])('reads the suffix of %s under -S %s as %s', (name, suffix, found) => {
  expect(gzipSuffix(name, suffix)).toBe(found)
})

it.each([
  ['.gz', false],
  ['', true],
  ['.' + 'a'.repeat(29), false],
  ['.' + 'a'.repeat(30), true],
])('takes a -S suffix of one to thirty bytes: %j', (suffix, refused) => {
  expect(suffixRefusal(suffix) !== null).toBe(refused)
})
