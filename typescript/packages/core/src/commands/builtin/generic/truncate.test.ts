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

import type { ByteSource, IOResult } from '../../../io/types.ts'
import { ContentType, FileStat, FileType, PathSpec } from '../../../types.ts'
import { enoent, enotdir } from '../../../utils/errors.ts'
import { UsageError } from '../../errors.ts'
import { truncateGeneric } from './truncate.ts'

function fPath(): PathSpec {
  return new PathSpec({
    virtual: '/f',
    directory: '/',
    vfsPath: 'f',
    resolved: true,
  })
}

async function runTruncate(size: string, current = 10): Promise<number[]> {
  const lengths: number[] = []
  await truncateGeneric(
    [fPath()],
    size,
    () =>
      Promise.resolve(
        new FileStat({ name: 'f', type: FileType.FILE, content: ContentType.TEXT, size: current }),
      ),
    (_p, length) => {
      lengths.push(length)
      return Promise.resolve()
    },
  )
  return lengths
}

describe('truncate sizes', () => {
  it('resolves plain and operation sizes', async () => {
    expect(await runTruncate('10', 0)).toEqual([10])
    expect(await runTruncate('+2', 10)).toEqual([12])
    expect(await runTruncate('-4', 10)).toEqual([6])
    expect(await runTruncate('<4', 10)).toEqual([4])
    expect(await runTruncate('>4', 10)).toEqual([10])
    expect(await runTruncate('%4', 10)).toEqual([12])
    expect(await runTruncate('/4', 10)).toEqual([8])
  })

  it('accepts the full GNU suffix alphabet', async () => {
    // truncate's letter set is not split's: lowercase g/k/m/t are valid
    // (pinned against coreutils 9.7), and E/P parse fine even though
    // most filesystems refuse the resulting size.
    expect(await runTruncate('1k')).toEqual([1024])
    expect(await runTruncate('1g')).toEqual([1024 ** 3])
    expect(await runTruncate('1t')).toEqual([1024 ** 4])
    expect(await runTruncate('1GiB')).toEqual([1024 ** 3])
    expect(await runTruncate('1GB')).toEqual([1000 ** 3])
    expect(await runTruncate('1mB')).toEqual([1000 ** 2])
    expect(await runTruncate('1E')).toEqual([1024 ** 6])
  })

  it('skips whitespace around the mode character', async () => {
    // GNU skips C-locale whitespace both before and after the mode char,
    // so ` 4` is absolute, ` +4` extends, and `< 4` caps (pinned against
    // coreutils 9.7).
    expect(await runTruncate(' 4', 10)).toEqual([4])
    expect(await runTruncate('  8', 0)).toEqual([8])
    expect(await runTruncate(' +4', 10)).toEqual([14])
    expect(await runTruncate(' -4', 10)).toEqual([6])
    expect(await runTruncate(' <4', 10)).toEqual([4])
    expect(await runTruncate('\t2k', 0)).toEqual([2048])
    expect(await runTruncate('< 4', 10)).toEqual([4])
    expect(await runTruncate('<  4', 10)).toEqual([4])
    expect(await runTruncate('% 512', 10)).toEqual([512])
    expect(await runTruncate('/ 2', 10)).toEqual([10])
    expect(await runTruncate('> 4', 10)).toEqual([10])
    expect(await runTruncate('\t<\t4', 10)).toEqual([4])
    expect(await runTruncate('< 10K', 10)).toEqual([10])
  })

  // A sign after <, >, / or % is refused as a second relative modifier
  // before the number is read, not reported as an invalid number.
  it.each(['<+4', '< +4', '<-4', '%+4', '>-4', '<\t+4'])(
    "refuses '%s' as multiple relative modifiers",
    async (value) => {
      await expect(runTruncate(value)).rejects.toThrow(
        new UsageError(
          "truncate: multiple relative modifiers specified\nTry 'truncate --help' for more information.",
          1,
        ),
      )
    },
  )

  // The digits must follow the sign immediately: no second sign, no gap,
  // and no trailing whitespace. GNU quotes the remainder past the skipped
  // whitespace and mode character, sign included. Deliberate divergence:
  // GNU's quotearg escapes control characters ('4\t' prints as '4\\t');
  // mirage quotes the raw remainder.
  it.each([
    ['abc', 'abc'],
    ['', ''],
    ['1x1K', '1x1K'],
    ['2b', '2b'],
    ['5c', '5c'],
    ['1e', '1e'],
    ['+ 4', '+ 4'],
    ['++4', '++4'],
    ['+4 ', '+4 '],
    ['4 ', '4 '],
    ['4\t', '4\t'],
    ['10 K', '10 K'],
    [' ', ''],
    [' abc', 'abc'],
    ['<abc', 'abc'],
    ['<', ''],
    ['< ', ''],
    ['<4 ', '4 '],
    ['4B', '4B'],
    ['4iB', '4iB'],
    ['0x10', '0x10'],
  ])("rejects '%s' as an invalid number without touching the file", async (value, quoted) => {
    const truncateCalls: number[] = []
    await expect(
      truncateGeneric(
        [fPath()],
        value,
        () =>
          Promise.resolve(
            new FileStat({ name: 'f', type: FileType.FILE, content: ContentType.TEXT, size: 10 }),
          ),
        (_p, length) => {
          truncateCalls.push(length)
          return Promise.resolve()
        },
      ),
    ).rejects.toThrow(new UsageError(`truncate: Invalid number: '${quoted}'`, 1))
    expect(truncateCalls).toEqual([])
  })

  it('reports off_t overflow with the Value-too-large tail', async () => {
    await expect(runTruncate('1Z')).rejects.toThrow(
      new UsageError("truncate: Invalid number: '1Z': Value too large for defined data type", 1),
    )
  })

  it('bounds off_t asymmetrically', async () => {
    // off_t is signed: 2**63 is one too large upward but fine downward.
    expect(await runTruncate('8191P', 0)).toEqual([8191 * 1024 ** 5])
    expect(await runTruncate('-8E', 10)).toEqual([0])
    expect(await runTruncate('-9223372036854775808', 10)).toEqual([0])
    await expect(runTruncate('8E')).rejects.toThrow(
      new UsageError("truncate: Invalid number: '8E': Value too large for defined data type", 1),
    )
    await expect(runTruncate('9223372036854775808')).rejects.toThrow(
      new UsageError(
        "truncate: Invalid number: '9223372036854775808': Value too large for defined data type",
        1,
      ),
    )
  })

  it('rejects division by zero', async () => {
    await expect(runTruncate('/0')).rejects.toThrow(new UsageError('truncate: division by zero', 1))
  })
})

describe('truncate operands', () => {
  function operand(virtual: string, rawPath: string): PathSpec {
    return new PathSpec({ virtual, directory: '/', vfsPath: virtual.slice(1), rawPath })
  }

  it('settles a missing operand by the truncate op', async () => {
    // GNU opens with O_CREAT before it reads a size, so a stat that misses
    // is never the verdict: a bare name is created, `missing/` is the
    // open's EISDIR, and a relative size starts from nothing.
    const lengths: [string, number][] = []
    const stat = (path: PathSpec): Promise<FileStat> =>
      Promise.reject(path.rawPath.startsWith('/under') ? enotdir(path) : enoent(path))
    const truncate = (path: PathSpec, length: number): Promise<void> => {
      lengths.push([path.rawPath, length])
      return Promise.resolve()
    }
    const [, io] = (await truncateGeneric(
      [
        operand('/missing', '/missing/'),
        operand('/missing', '/missing'),
        operand('/under/x', '/under/x'),
      ],
      '+4',
      stat,
      truncate,
    )) as [ByteSource | null, IOResult]
    expect(lengths).toEqual([
      ['/missing/', 4],
      ['/missing', 4],
      ['/under/x', 4],
    ])
    expect(io.exitCode).toBe(0)
    expect(io.stderr).toBeNull()
  })

  it('reports a failed open and still runs the rest', async () => {
    // One GNU line per operand the open refuses, the name always quoted
    // (quoteaf), and every other operand still truncated.
    const lengths: [string, number][] = []
    const stat = (path: PathSpec): Promise<FileStat> => Promise.reject(enoent(path))
    const truncate = (path: PathSpec, length: number): Promise<void> => {
      if (path.rawPath !== 'b') return Promise.reject(enoent(path))
      lengths.push([path.rawPath, length])
      return Promise.resolve()
    }
    const [, io] = (await truncateGeneric(
      [operand('/nope/x', 'nope/x'), operand('/b', 'b'), operand("/it's/x", "it's/x")],
      '2',
      stat,
      truncate,
    )) as [ByteSource | null, IOResult]
    expect(lengths).toEqual([['b', 2]])
    expect(io.exitCode).toBe(1)
    expect(new TextDecoder().decode(io.stderr as Uint8Array)).toBe(
      "truncate: cannot open 'nope/x' for writing: No such file or directory\n" +
        'truncate: cannot open "it\'s/x" for writing: No such file or directory\n',
    )
  })

  it('leaves a missing operand alone under -c', async () => {
    // -c opens without O_CREAT: the open's ENOENT is silence whether the file
    // or its parent is missing, a parent that is a file is still refused, and
    // an operand that is there is truncated.
    const lengths: [string, number][] = []
    const stat = (path: PathSpec): Promise<FileStat> => {
      if (path.rawPath === 'f.txt/x') return Promise.reject(enotdir(path))
      if (path.rawPath === 'have') {
        return Promise.resolve(new FileStat({ name: 'have', type: FileType.FILE, size: 6 }))
      }
      return Promise.reject(enoent(path))
    }
    const truncate = (path: PathSpec, length: number): Promise<void> => {
      lengths.push([path.rawPath, length])
      return Promise.resolve()
    }
    const [, io] = (await truncateGeneric(
      [
        operand('/gone', 'gone'),
        operand('/nope/x', 'nope/x'),
        operand('/f.txt/x', 'f.txt/x'),
        operand('/have', 'have'),
      ],
      '-2',
      stat,
      truncate,
      true,
    )) as [ByteSource | null, IOResult]
    expect(lengths).toEqual([['have', 4]])
    expect(io.exitCode).toBe(1)
    expect(new TextDecoder().decode(io.stderr as Uint8Array)).toBe(
      "truncate: cannot open 'f.txt/x' for writing: Not a directory\n",
    )
  })

  it('refuses a bad size before any operand is looked at', async () => {
    // GNU parses -s with its options, so -c skipping every operand does not
    // skip the refusal.
    const lookedAt: string[] = []
    const stat = (path: PathSpec): Promise<FileStat> => {
      lookedAt.push(path.rawPath)
      return Promise.reject(enoent(path))
    }
    const truncate = (path: PathSpec): Promise<void> => {
      lookedAt.push(path.rawPath)
      return Promise.resolve()
    }
    await expect(
      truncateGeneric([operand('/gone', 'gone')], '<abc', stat, truncate, true),
    ).rejects.toThrow(new UsageError("truncate: Invalid number: 'abc'", 1))
    expect(lookedAt).toEqual([])
  })
})
