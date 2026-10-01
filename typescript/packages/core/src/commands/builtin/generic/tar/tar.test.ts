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

// Mirrors python/tests/commands/builtin/generic/tar/test_tar.py.

import { beforeAll, describe, expect, it } from 'vitest'
import { gzip } from '../../../../utils/compress.ts'
import { MountMode } from '../../../../types.ts'
import { RAMVFS } from '../../../../vfs/ram/ram.ts'
import { getTestParser } from '../../../../workspace/fixtures/workspace_fixture.ts'
import { Workspace } from '../../../../workspace/workspace/workspace.ts'
import { writeTar } from '../../tar_helper.ts'
import { UsageError } from '../../../errors.ts'
import { parseCommand, specOf } from '../../../spec/index.ts'
import { parseToKwargs } from '../../../spec/parser.ts'
import { MODE_CONFLICT, MULTIPLE_ARCHIVES } from './constants.ts'
import { parseTarFlags, stripCount } from './tar.ts'

const ENC = new TextEncoder()
const DEC = new TextDecoder()
const CHILD_FAILED = 'tar: Child returned status 1\ntar: Error is not recoverable: exiting now\n'

let OK: Uint8Array = new Uint8Array()
// The same archive with its CRC-32 and length trailer zeroed.
let DAMAGED = new Uint8Array()

beforeAll(async () => {
  OK = await gzip(
    await writeTar([
      { name: 'd/a.txt', data: ENC.encode('hello\n'), isFile: true },
      { name: 'd/b.txt', data: ENC.encode('bee\n'), isFile: true },
    ]),
  )
  DAMAGED = new Uint8Array([...OK.subarray(0, -8), 0, 0, 0, 0, 0, 0, 0, 0])
})

async function shell(
  line: string,
  seed: Record<string, Uint8Array>,
): Promise<[number, string, string]> {
  const ws = new Workspace(
    { '/data/': new RAMVFS() },
    { mode: MountMode.WRITE, shellParser: await getTestParser() },
  )
  try {
    for (const [path, data] of Object.entries(seed)) {
      await ws.shell(`tee ${path} > /dev/null`, { stdin: data })
    }
    const io = await ws.shell(line)
    return [io.exitCode, DEC.decode(io.stdout), DEC.decode(io.stderr)]
  } finally {
    await ws.close()
  }
}

describe('tar over a gzip child that fails', () => {
  it("is gzip's refusal, then tar's, for a non-gzip archive", async () => {
    // GNU tar 1.35 reads -z through a gzip -d child and dies when it
    // fails, after gzip's own line.
    const r = await shell('tar -tzf /data/c.tgz', { '/data/c.tgz': ENC.encode('corrupted\n') })
    expect(r).toEqual([2, '', '\ngzip: stdin: not in gzip format\n' + CHILD_FAILED])
  })

  it('still yields every member past a damaged trailer', async () => {
    const seed = { '/data/bad.tgz': DAMAGED }
    const reasons =
      '\ngzip: stdin: invalid compressed data--crc error\n' +
      '\ngzip: stdin: invalid compressed data--length error\n'
    expect(await shell('tar -tzf /data/bad.tgz nomatch', seed)).toEqual([
      2,
      '',
      reasons + CHILD_FAILED,
    ])
    expect(await shell('tar -xzf /data/bad.tgz -C /data; cat /data/d/*', seed)).toEqual([
      0,
      'hello\nbee\n',
      reasons + CHILD_FAILED,
    ])
  })

  it('takes the same road on the gzip magic without -z', async () => {
    const r = await shell('tar -tf /data/junk.tgz', {
      '/data/junk.tgz': new Uint8Array([...OK, ...ENC.encode('xy')]),
    })
    expect(r).toEqual([
      2,
      'd/a.txt\nd/b.txt\n',
      '\ngzip: stdin: decompression OK, trailing garbage ignored\n' +
        'tar: Child returned status 2\n' +
        'tar: Error is not recoverable: exiting now\n',
    ])
  })

  it('yields nothing from a member cut short', async () => {
    const r = await shell('tar -tzf /data/cut.tgz', { '/data/cut.tgz': OK.subarray(0, -40) })
    expect(r).toEqual([2, '', '\ngzip: stdin: unexpected end of file\n' + CHILD_FAILED])
  })
})

it.each(['-tzf', '-tf', '-xOzf'])(
  'keeps complete tar members with a truncated gzip wrapper: %s',
  async (flags) => {
    for (const data of [
      OK.subarray(0, -8),
      OK.subarray(0, -3),
      new Uint8Array([...OK, ...OK.subarray(0, 2)]),
    ]) {
      const out = flags === '-xOzf' ? 'hello\nbee\n' : 'd/a.txt\nd/b.txt\n'
      expect(await shell(`tar ${flags} /data/cut.tgz`, { '/data/cut.tgz': data })).toEqual([
        2,
        out,
        '\ngzip: stdin: unexpected end of file\n' + CHILD_FAILED,
      ])
    }
  },
)

it('extracts complete tar members despite a truncated gzip trailer', async () => {
  expect(
    await shell('tar -xzf /data/cut.tgz -C /data; cat /data/d/*', {
      '/data/cut.tgz': OK.subarray(0, -3),
    }),
  ).toEqual([0, 'hello\nbee\n', '\ngzip: stdin: unexpected end of file\n' + CHILD_FAILED])
})

it.each(['-tzf', '-xzf', '-xOzf'])(
  'preserves both gzip and tar diagnostics when parsing fails: %s',
  async (flags) => {
    for (const size of [9, 512, 1024]) {
      const bad = await gzip(new Uint8Array(size).fill(120))
      bad.fill(0, bad.length - 8)
      const notices =
        size >= 512
          ? 'tar: This does not look like a tar archive\ntar: Skipping to next header\n'
          : ''
      expect(await shell(`tar ${flags} /data/bad.tgz`, { '/data/bad.tgz': bad })).toEqual([
        2,
        '',
        '\ngzip: stdin: invalid compressed data--crc error\n' +
          '\ngzip: stdin: invalid compressed data--length error\n' +
          notices +
          CHILD_FAILED,
      ])
    }
  },
)

it.each(['t', 'x', 'c'])('preserves empty and looping archive names for -%sf', async (mode) => {
  for (const [name, reason] of [
    ['', 'No such file or directory'],
    ['loop', 'Too many levels of symbolic links'],
  ] as const) {
    const result = await shell(`cd /data; ln -s loop loop; tar -${mode}f '${name}' a.txt`, {
      '/data/a.txt': ENC.encode('hello\n'),
    })
    expect(result).toEqual([
      2,
      '',
      `tar: ${name}: Cannot open: ${reason}\ntar: Error is not recoverable: exiting now\n`,
    ])
  }
})

it('keeps the empty archive refusal across mounts', async () => {
  const ws = new Workspace(
    { '/data': new RAMVFS(), '/other': new RAMVFS() },
    { mode: MountMode.WRITE, shellParser: await getTestParser() },
  )
  try {
    await ws.shell('echo hello > /other/a.txt')
    const result = await ws.shell("cd /data; tar -cf '' /other/a.txt")
    expect(result.exitCode).toBe(2)
    expect(DEC.decode(result.stderr)).toBe(
      'tar: : Cannot open: No such file or directory\ntar: Error is not recoverable: exiting now\n',
    )
  } finally {
    await ws.close()
  }
})

describe("tar's argp refusals", () => {
  // argp stops at the first refusal in line order (tar 1.35). Mirrors
  // python's test_parse_flags_refuses_what_tar_refuses.
  it.each([
    [['-c', '-x'], MODE_CONFLICT],
    [['-x', '--list'], MODE_CONFLICT],
    [['--strip-components=x', '-c', '-x'], 'tar: x: Invalid number of elements'],
    [['-c', '-x', '--strip-components=x'], MODE_CONFLICT],
    [['-t', '-f', '/a', '-f', '/a'], MULTIPLE_ARCHIVES],
    [['-t', '--strip-components=-1'], 'tar: -1: Invalid number of elements'],
    [['-t', '--strip-components='], 'tar: : Invalid number of elements'],
    [
      ['-t', '--strip-components=99999999999999999999'],
      'tar: 99999999999999999999: Invalid number of elements',
    ],
  ])('%j', (words, message) => {
    const flags = parseToKwargs(parseCommand(specOf('tar'), words, '/', 'tar'))
    expect(() => parseTarFlags(flags)).toThrow(
      new UsageError(`${message}\nTry 'tar --help' for more information.`),
    )
  })

  it.each([
    ['0', 0],
    ['+1', 1],
    [' 2', 2],
    ['010', 10],
  ])('reads the strip count %j at base ten', (raw, count) => {
    expect(stripCount(raw)).toBe(count)
  })
})

describe("tar's long options", () => {
  // Mirrors python's test_tars_long_options_run_as_the_short_ones.
  it.each([
    ['tar --create --file=a.tar a.txt && tar --list --file a.tar', 'a.txt\n'],
    ['tar -cf a.tar a.txt && tar --get -f a.tar --directory=dir && ls dir', 'a.txt\n'],
    ['tar --create --gzip --file=a.tgz a.txt && tar -t --gun -f a.tgz', 'a.txt\n'],
  ])('%s', async (line, out) => {
    const [code, stdout] = await shell(`mkdir /data/dir && cd /data && ${line}`, {
      '/data/a.txt': new TextEncoder().encode('x\n'),
    })
    expect([code, stdout]).toEqual([0, out])
  })
})

it('streams an archive without a writable root or a dash file', async () => {
  const ws = new Workspace(
    { '/data': [new RAMVFS(), MountMode.WRITE] },
    {
      mode: MountMode.READ,
      shellParser: await getTestParser(),
    },
  )
  await ws.shell('printf hello > /data/a')
  const result = await ws.shell('tar -cvf - -C /data a | tar -xOf -')
  expect(result.exitCode).toBe(0)
  expect(DEC.decode(result.stdout)).toBe('hello')
  expect(DEC.decode(result.stderr)).toBe('a\n')
  expect((await ws.shell('test ! -e /-')).exitCode).toBe(0)
  await ws.close()
})

it.each(['', 'not an archive', 'x'.repeat(1024)])('rejects non-archive bytes %s', async (text) => {
  for (const flags of ['-tf', '-xf']) {
    const notices =
      'tar: This does not look like a tar archive\n' +
      (text.length >= 512 ? 'tar: Skipping to next header\n' : '')
    expect(await shell(`tar ${flags} /data/bad`, { '/data/bad': ENC.encode(text) })).toEqual([
      2,
      '',
      notices + 'tar: Exiting with failure status due to previous errors\n',
    ])
  }
})
