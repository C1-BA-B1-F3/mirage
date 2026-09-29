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
import { OpsRegistry } from '../../../ops/registry.ts'
import { MountMode } from '../../../types.ts'
import { RAMVFS } from '../../../vfs/ram/ram.ts'
import { getTestParser } from '../../../workspace/fixtures/workspace_fixture.ts'
import { Workspace } from '../../../workspace/workspace/workspace.ts'
import { GENERAL_DATE } from './date.ts'

const DEC = new TextDecoder()

async function runDate(
  texts: string[] = [],
  flags: Record<string, string | boolean | number | string[]> = {},
): Promise<string> {
  const vfs = new RAMVFS()
  const cmd = GENERAL_DATE[0]
  if (cmd === undefined) throw new Error('date not registered')
  const result = await cmd.fn((vfs as { accessor?: unknown }).accessor as never, [], texts, {
    stdin: null,
    flags,
    filetypeFns: null,
    cwd: '/',
  })
  if (result === null) return ''
  const [out] = result
  if (out === null) return ''
  const buf = out instanceof Uint8Array ? out : await materialize(out as AsyncIterable<Uint8Array>)
  return DEC.decode(buf)
}

describe('date', () => {
  it('-I returns ISO date', async () => {
    const fixed = '2026-04-21T12:00:00Z'
    const out = await runDate([], { date: fixed, iso_8601: true })
    expect(out).toBe('2026-04-21\n')
  })

  it('-d with custom format', async () => {
    const out = await runDate(['+%Y-%m-%d'], { date: '2026-04-21T12:00:00Z', utc: true })
    expect(out).toBe('2026-04-21\n')
  })

  it('+%H:%M:%S UTC', async () => {
    const out = await runDate(['+%H:%M:%S'], { date: '2026-04-21T13:45:30Z', utc: true })
    expect(out).toBe('13:45:30\n')
  })

  it('default format roughly matches "Day Mon DD HH:MM:SS YYYY"', async () => {
    const out = await runDate([], { date: '2026-04-21T12:00:00', utc: true })
    // Tue Apr 21 12:00:00 UTC 2026
    expect(out).toMatch(/^[A-Z][a-z]{2} [A-Z][a-z]{2} \d{2} \d{2}:\d{2}:\d{2} (UTC )?2026\n$/)
  })

  it('-R RFC5322 format', async () => {
    const out = await runDate([], { date: '2026-04-21T12:00:00Z', utc: true, rfc_email: true })
    expect(out).toBe('Tue, 21 Apr 2026 12:00:00 +0000\n')
  })

  it('+%s seconds since epoch', async () => {
    const out = await runDate(['+%s'], { date: '2026-04-21T00:00:00Z', utc: true })
    // 2026-04-21T00:00:00Z = 1777305600
    expect(out.trim()).toBe(String(Math.floor(Date.UTC(2026, 3, 21) / 1000)))
  })
})

async function runDateIo(
  texts: string[] = [],
  flags: Record<string, string | boolean | number | string[]> = {},
): Promise<[string, string, number]> {
  const vfs = new RAMVFS()
  const cmd = GENERAL_DATE[0]
  if (cmd === undefined) throw new Error('date not registered')
  const result = await cmd.fn((vfs as { accessor?: unknown }).accessor as never, [], texts, {
    stdin: null,
    flags,
    filetypeFns: null,
    cwd: '/',
  })
  if (result === null) return ['', '', 0]
  const [out, io] = result
  const buf =
    out === null
      ? new Uint8Array()
      : out instanceof Uint8Array
        ? out
        : await materialize(out as AsyncIterable<Uint8Array>)
  const errRaw =
    io.stderr === null
      ? new Uint8Array()
      : io.stderr instanceof Uint8Array
        ? io.stderr
        : await materialize(io.stderr as AsyncIterable<Uint8Array>)
  return [DEC.decode(buf), DEC.decode(errRaw), io.exitCode]
}

describe('date GNU format specifiers', () => {
  const AT = '2026-08-16T13:45:30Z'

  it('+%F renders the ISO date, not the literal', async () => {
    expect(await runDate(['+%F %T'], { date: AT, utc: true })).toBe('2026-08-16 13:45:30\n')
  })

  it('renders 12-hour, quarter, century, and padded-hour forms', async () => {
    expect(await runDate(['+%r|%q|%C|%h|%k|%l|%P|%R'], { date: AT, utc: true })).toBe(
      '01:45:30 PM|3|20|Aug|13| 1|pm|13:45\n',
    )
  })

  it('renders week numbers and the ISO week-based year', async () => {
    expect(await runDate(['+%V|%U|%W|%G|%g'], { date: AT, utc: true })).toBe('33|33|32|2026|26\n')
  })

  it('renders C-locale %c, %x, %X and the %n/%t escapes', async () => {
    expect(await runDate(['+%c|%x|%X|%n|%t'], { date: AT, utc: true })).toBe(
      'Sun Aug 16 13:45:30 2026|08/16/26|13:45:30|\n|\t\n',
    )
  })

  it('passes an unknown directive through literally, as GNU does', async () => {
    expect(await runDate(['+%v'], { date: AT, utc: true })).toBe('%v\n')
  })
})

describe('date -d expressions', () => {
  it('handles a relative displacement from an ISO base', async () => {
    const out = await runDate(['+%F %T'], { date: '2026-08-16 12:00:00 24 hours ago', utc: true })
    expect(out).toBe('2026-08-15 12:00:00\n')
  })

  it('handles @epoch input', async () => {
    expect(await runDate(['+%F %T'], { date: '@1755300000', utc: true })).toBe(
      '2025-08-15 23:20:00\n',
    )
  })

  it('normalizes month overflow the way GNU does', async () => {
    expect(await runDate(['+%F'], { date: '2026-01-31 1 month', utc: true })).toBe('2026-03-03\n')
  })

  it('produces a date, never NaN, for a bare relative expression', async () => {
    const out = await runDate(['+%F'], { date: '24 hours ago', utc: true })
    expect(out).toMatch(/^\d{4}-\d{2}-\d{2}\n$/)
  })

  it('refuses an invalid date with GNU wording and exit 1', async () => {
    const [out, stderr, code] = await runDateIo([], { date: 'not a date' })
    expect(out).toBe('')
    expect(stderr).toBe("date: invalid date 'not a date'\n")
    expect(code).toBe(1)
  })

  // GNU ACCEPTS an empty (or blank) `-d`, exit 0, at today 00:00:00:
  // gnulib's parse-datetime sees no component at all and falls through to
  // "a date with no time". Measured on coreutils 9.4 under
  // `LC_ALL=C TZ=UTC`. mirage used to answer `date: invalid date ''` and
  // exit 1. Mirrors test_date.py.
  it.each(['', '   '])('reads %j as today at midnight', async (d) => {
    const [out, stderr, code] = await runDateIo(['+%H:%M:%S'], { date: d, utc: true })
    expect([out, stderr, code]).toEqual(['00:00:00\n', '', 0])
    const day = await runDate(['+%Y-%m-%d'], { date: d, utc: true })
    expect(day).toBe(await runDate(['+%Y-%m-%d'], { utc: true }))
  })
})

async function runDateEnv(
  env: Record<string, string>,
  texts: string[] = [],
  flags: Record<string, string | boolean | number | string[]> = {},
): Promise<[string, string, number]> {
  const vfs = new RAMVFS()
  const cmd = GENERAL_DATE[0]
  if (cmd === undefined) throw new Error('date not registered')
  const result = await cmd.fn((vfs as { accessor?: unknown }).accessor as never, [], texts, {
    stdin: null,
    flags,
    filetypeFns: null,
    cwd: '/',
    env,
  })
  if (result === null) return ['', '', 0]
  const [out, io] = result
  const buf =
    out === null
      ? new Uint8Array()
      : out instanceof Uint8Array
        ? out
        : await materialize(out as AsyncIterable<Uint8Array>)
  const err = io.stderr === null ? new Uint8Array() : await materialize(io.stderr)
  return [DEC.decode(buf), DEC.decode(err), io.exitCode]
}

// Pinned against GNU date 9.x on debian:stable-slim with tzdata: the zone
// is the command environment's TZ, `-u` outranks it, and an instant
// renders on the calendar day the zone shows (issue #1070). The zone comes
// from `opts.env` alone: process.env.TZ is never read or written.
describe('date honors the command environment TZ', () => {
  it.each([
    [{ TZ: 'UTC' }, ['+%Y-%m-%d %H:%M:%S %z'], { date: '@0' }, '1970-01-01 00:00:00 +0000\n'],
    [
      { TZ: 'Asia/Hong_Kong' },
      ['+%Y-%m-%d %H:%M:%S %z'],
      { date: '@0' },
      '1970-01-01 08:00:00 +0800\n',
    ],
    [
      { TZ: 'Asia/Hong_Kong' },
      ['+%F %T %z %Z'],
      { date: '@0', utc: true },
      '1970-01-01 00:00:00 +0000 UTC\n',
    ],
    [
      { TZ: 'Asia/Hong_Kong' },
      ['+%F %T'],
      { date: '1970-01-01T20:00:00Z' },
      '1970-01-02 04:00:00\n',
    ],
    [
      { TZ: 'Asia/Hong_Kong' },
      ['+%F %T'],
      { date: '1970-01-01T20:00:00Z 1 day' },
      '1970-01-03 04:00:00\n',
    ],
    [{ TZ: 'Asia/Hong_Kong' }, ['+%s'], { date: '1970-01-01 00:00:00' }, '-28800\n'],
    [
      { TZ: 'Asia/Hong_Kong' },
      [],
      { date: '@0', rfc_email: true },
      'Thu, 01 Jan 1970 08:00:00 +0800\n',
    ],
    [
      { TZ: 'Asia/Hong_Kong' },
      [],
      { date: '1970-01-01T20:00:00Z', iso_8601: true },
      '1970-01-02\n',
    ],
    [
      { TZ: 'America/Los_Angeles' },
      ['+%F %T %z'],
      { date: '@1751328000' },
      '2025-06-30 17:00:00 -0700\n',
    ],
    [{ TZ: 'Bogus/Zone' }, ['+%F %T %z %Z'], { date: '@0' }, '1970-01-01 00:00:00 +0000 Bogus\n'],
    [{ TZ: ':Asia/Tokyo' }, ['+%T %z'], { date: '@0' }, '09:00:00 +0900\n'],
    [{ TZ: 'UTC0' }, ['+%T %z %Z'], { date: '@0' }, '00:00:00 +0000 UTC\n'],
    [{ TZ: '<+0530>-5:30' }, ['+%T %z %Z %:z'], { date: '@0' }, '05:30:00 +0530 +0530 +05:30\n'],
    [
      { TZ: 'CET-1CEST,M3.5.0,M10.5.0/3' },
      ['+%F %T %z %Z'],
      { date: '@1751328000' },
      '2025-07-01 02:00:00 +0200 CEST\n',
    ],
    [
      { TZ: 'CET-1CEST,M3.5.0,M10.5.0/3' },
      ['+%s %Z'],
      { date: '2025-10-26 02:30:00' },
      '1761442200 CET\n',
    ],
    [
      { TZ: 'CET-1CEST,M3.5.0,M10.5.0/3' },
      ['+%F %T %Z'],
      { date: '2025-03-29 12:00:00 1 day' },
      '2025-03-30 12:00:00 CEST\n',
    ],
    [
      { TZ: 'CET-1CEST,M3.5.0,M10.5.0/3' },
      ['+%F %T %Z'],
      { date: '2025-03-29 12:00:00 24 hours' },
      '2025-03-30 13:00:00 CEST\n',
    ],
    [{ TZ: 'UTC' }, ['+%a %Z'], { date: '@0' }, 'Thu UTC\n'],
    [{ TZ: 'UTC' }, [], { date: '@0' }, 'Thu Jan  1 00:00:00 UTC 1970\n'],
    [{ TZ: '' }, ['+%F %T %z'], { date: '@0' }, '1970-01-01 00:00:00 +0000\n'],
    // A day shift landing in the hour CEST skips moves past the gap, and one
    // landing in the hour it repeats keeps the base's side (gnulib hands
    // mktime the base's tm_isdst).
    [
      { TZ: 'Europe/Berlin' },
      ['+%F %T %z %Z'],
      { date: '2025-03-29 02:30:00 1 day' },
      '2025-03-30 03:30:00 +0200 CEST\n',
    ],
    [
      { TZ: 'Europe/Berlin' },
      ['+%F %T %z %Z'],
      { date: '2025-10-25 02:30:00 1 day' },
      '2025-10-26 02:30:00 +0200 CEST\n',
    ],
    [
      { TZ: 'Europe/Berlin' },
      ['+%F %T %z %Z'],
      { date: '2025-10-27 02:30:00 1 day ago' },
      '2025-10-26 02:30:00 +0100 CET\n',
    ],
    // glibc keeps the names and offsets of a POSIX string whose rule it
    // refuses, and clamps an offset's minutes at 59.
    [{ TZ: 'CET-1CEST,bogus' }, ['+%z %Z'], { date: '@1720000000' }, '+0200 CEST\n'],
    [{ TZ: 'UTC5:99' }, ['+%T %z'], { date: '@0' }, '18:01:00 -0559\n'],
  ])('%j %j %j', async (env, texts, flags, expected) => {
    expect(await runDateEnv(env, texts, flags)).toEqual([expected, '', 0])
  })

  it('refuses a wall clock the zone skips', async () => {
    // glibc's mktime finds no instant for 02:30 on the night CEST starts.
    expect(
      await runDateEnv({ TZ: 'Europe/Berlin' }, ['+%s'], { date: '2025-03-30 02:30:00' }),
    ).toEqual(['', "date: invalid date '2025-03-30 02:30:00'\n", 1])
  })

  it('reads each invocation its own zone with no process state between them', async () => {
    const before = process.env.TZ
    const results = await Promise.all([
      runDateEnv({ TZ: 'Asia/Hong_Kong' }, ['+%H %z'], { date: '@0' }),
      runDateEnv({ TZ: 'UTC' }, ['+%H %z'], { date: '@0' }),
      runDateEnv({ TZ: 'Asia/Hong_Kong' }, ['+%H %z'], { date: '@0' }),
      runDateEnv({}, ['+%H %z'], { date: '@0', utc: true }),
    ])
    expect(results.map((r) => r[0])).toEqual([
      '08 +0800\n',
      '00 +0000\n',
      '08 +0800\n',
      '00 +0000\n',
    ])
    expect(process.env.TZ).toBe(before)
  })
})

// `%Z` is tzdata's abbreviation in both hosts (GNU date on
// debian:stable-slim): lettered where tzdata has letters, the offset
// spelled out where it does not, and a zone's own history applies.
describe("date: %Z is tzdata's abbreviation", () => {
  it.each([
    [{ TZ: 'Asia/Hong_Kong' }, ['+%Z'], { date: '@0' }, 'HKT\n'],
    [{ TZ: 'Europe/London' }, ['+%Z'], { date: '@1751328000' }, 'BST\n'],
    [{ TZ: 'Europe/London' }, ['+%Z'], { date: '@1735689600' }, 'GMT\n'],
    [{ TZ: 'Australia/Sydney' }, ['+%Z'], { date: '@1751328000' }, 'AEST\n'],
    [{ TZ: 'Australia/Sydney' }, ['+%Z'], { date: '@1735689600' }, 'AEDT\n'],
    [{ TZ: 'Asia/Kolkata' }, ['+%Z %z'], { date: '@0' }, 'IST +0530\n'],
    [{ TZ: 'Asia/Singapore' }, ['+%Z'], { date: '@0' }, '+0730\n'],
    [{ TZ: 'Asia/Singapore' }, ['+%Z'], { date: '@1751328000' }, '+08\n'],
    [{ TZ: 'America/Sao_Paulo' }, ['+%Z'], { date: '@0' }, '-03\n'],
    [{ TZ: 'Etc/GMT+5' }, ['+%Z'], { date: '@0' }, '-05\n'],
    [{ TZ: 'Europe/Moscow' }, ['+%Z %z'], { date: '@1340000000' }, 'MSK +0400\n'],
    [{ TZ: 'Europe/Moscow' }, ['+%Z %z'], { date: '@1276848800' }, 'MSD +0400\n'],
    [{ TZ: 'Europe/Istanbul' }, ['+%Z'], { date: '@1435752000' }, 'EEST\n'],
    [{ TZ: 'Europe/Istanbul' }, ['+%Z'], { date: '@1498906800' }, '+03\n'],
  ])('%j %j %j', async (env, texts, flags, expected) => {
    expect(await runDateEnv(env, texts, flags)).toEqual([expected, '', 0])
  })
})

it('renders the implicit host zone in explicit and default formats', async () => {
  const hostZone = new Intl.DateTimeFormat().resolvedOptions().timeZone
  for (const d of ['@1789430400', '@1767225600']) {
    for (const format of [[], ['+%Z %z']]) {
      const implicit = await runDateEnv({}, format, { date: d })
      expect(implicit).toEqual(await runDateEnv({ TZ: hostZone }, format, { date: d }))
      expect(implicit[0].trim()).not.toBe('')
    }
  }
})

// `date -d` names the refused expression through gnulib's quote(), so a
// byte outside 0x20-0x7e comes back escaped rather than interpolated raw.
// Every row measured against GNU coreutils 9.4 under `LC_ALL=C` with a raw
// `bytes` argv (`date -d x<B>`). Mirrors test_date.py.
async function runDateStderr(d: string): Promise<[string, number]> {
  const vfs = new RAMVFS()
  const cmd = GENERAL_DATE[0]
  if (cmd === undefined) throw new Error('date not registered')
  const result = await cmd.fn((vfs as { accessor?: unknown }).accessor as never, [], [], {
    stdin: null,
    flags: { date: d },
    filetypeFns: null,
    cwd: '/',
  })
  if (result === null) throw new Error('date returned no result')
  const [, io] = result
  return [DEC.decode(io.stderr as Uint8Array), io.exitCode]
}

describe('date quotes the expression it refuses', () => {
  it.each([
    ['xé', 'x\\303\\251'],
    ['x\r', 'x\\r'],
    ['x\x01', 'x\\001'],
    ['x\x7f', 'x\\177'],
    ["x'", "x\\'"],
    ['x\\', 'x\\\\'],
  ])('escapes %j in the invalid-date clause', async (value, escaped) => {
    expect(await runDateStderr(value)).toEqual([`date: invalid date '${escaped}'\n`, 1])
  })
})

describe('date output formats through the shell', () => {
  // GNU's output formats, one per option, measured on coreutils 9.7
  // (debian:stable-slim): -I[FMT] takes its precision attached or after `=`
  // and matches it by prefix, --rfc-3339=FMT takes the narrower set, and a
  // line with no format option prints `%e`, a space-padded day. Mirrors
  // test_date.py.
  const AT = '2024-03-05T07:08:09.5Z'
  const ISO_VALID =
    "Valid arguments are:\n  - 'hours'\n  - 'minutes'\n  - 'date'\n  - 'seconds'\n  - 'ns'\n" +
    "Try 'date --help' for more information.\n"
  const MULTIPLE = 'date: multiple output formats specified\n'

  async function makeWs(): Promise<Workspace> {
    const parser = await getTestParser()
    const ram = new RAMVFS()
    const registry = new OpsRegistry()
    registry.registerVfs(ram)
    return new Workspace(
      { '/ram': ram },
      { mode: MountMode.WRITE, ops: registry, shellParser: parser },
    )
  }

  it.each([
    [`date -u -d ${AT} -I`, '2024-03-05\n'],
    [`date -u -d ${AT} -Id`, '2024-03-05\n'],
    [`date -u -d ${AT} -Ih`, '2024-03-05T07+00:00\n'],
    [`date -u -d ${AT} -Im`, '2024-03-05T07:08+00:00\n'],
    [`date -u -d ${AT} -Is`, '2024-03-05T07:08:09+00:00\n'],
    [`date -u -d ${AT} -Ins`, '2024-03-05T07:08:09,500000000+00:00\n'],
    [`date -u -d ${AT} -Isec`, '2024-03-05T07:08:09+00:00\n'],
    [`date -u -d ${AT} -Iho`, '2024-03-05T07+00:00\n'],
    [`date -d ${AT} -uIs`, '2024-03-05T07:08:09+00:00\n'],
    [`date -u -d ${AT} --iso-8601`, '2024-03-05\n'],
    [`date -u -d ${AT} --iso-8601=seconds`, '2024-03-05T07:08:09+00:00\n'],
    [`date -u -d ${AT} --iso=m`, '2024-03-05T07:08+00:00\n'],
    [`TZ=Asia/Kolkata date -d ${AT} -Is`, '2024-03-05T12:38:09+05:30\n'],
    [`TZ=America/St_Johns date -d ${AT} -Im`, '2024-03-05T03:38-03:30\n'],
    [`date -u -d ${AT} --rfc-3339=date`, '2024-03-05\n'],
    [`date -u -d ${AT} --rfc-3339=seconds`, '2024-03-05 07:08:09+00:00\n'],
    [`date -u -d ${AT} --rfc-3339=ns`, '2024-03-05 07:08:09.500000000+00:00\n'],
    [`date --utc --date=${AT} --rfc-email`, 'Tue, 05 Mar 2024 07:08:09 +0000\n'],
    [`date --universal -d ${AT} -I`, '2024-03-05\n'],
    [`date -u -d ${AT}`, 'Tue Mar  5 07:08:09 UTC 2024\n'],
  ])('%s', async (line, out) => {
    const ws = await makeWs()
    const io = await ws.shell(line)
    await ws.close()
    expect([io.stdoutText, io.stderrText, io.exitCode]).toEqual([out, '', 0])
  })

  it.each([
    [`date -d ${AT} -Ix`, "date: invalid argument 'x' for '--iso-8601'\n" + ISO_VALID],
    [`date -d ${AT} -Isu`, "date: invalid argument 'su' for '--iso-8601'\n" + ISO_VALID],
    [`date -d ${AT} --iso-8601=`, "date: ambiguous argument '' for '--iso-8601'\n" + ISO_VALID],
    [
      `date -d ${AT} --rfc-3339=hours`,
      "date: invalid argument 'hours' for '--rfc-3339'\n" +
        "Valid arguments are:\n  - 'date'\n  - 'seconds'\n  - 'ns'\n" +
        "Try 'date --help' for more information.\n",
    ],
    [
      `date -d ${AT} --rfc-3339`,
      "date: option '--rfc-3339' requires an argument\nTry 'date --help' for more information.\n",
    ],
    [`date -d ${AT} -I -R`, MULTIPLE],
    [`date -d ${AT} --rfc-3339=s -Is`, MULTIPLE],
    [`date -d ${AT} -Is +%Y`, MULTIPLE],
    [`date -d ${AT} -I -R a b`, MULTIPLE],
  ])('%s refuses', async (line, err) => {
    const ws = await makeWs()
    const io = await ws.shell(line)
    await ws.close()
    expect([io.stdoutText, io.stderrText, io.exitCode]).toEqual(['', err, 1])
  })

  // An operand without `+` sets the clock (coreutils 9.7, as a user without
  // the privilege to): a readable one prints the date it names and exits 1
  // with `cannot set date`, anything else is `invalid date`, and beside -d it
  // is a usage error. Mirrors test_date.py.
  const CANNOT_SET = 'date: cannot set date: Operation not permitted\n'
  it.each([
    ['date -u 010100002024', 'Mon Jan  1 00:00:00 UTC 2024\n', CANNOT_SET],
    ['date -u -I 0229000024', '2024-02-29\n', CANNOT_SET],
    ['date -u 1231235924.60', 'Wed Jan  1 00:00:00 UTC 2025\n', CANNOT_SET],
    ['date -I seconds', '', "date: invalid date 'seconds'\n"],
    ['date 0229000025', '', "date: invalid date '0229000025'\n"],
    ['TZ=Europe/Berlin date 033002302025', '', "date: invalid date '033002302025'\n"],
    [
      `date -d ${AT} x`,
      '',
      "date: the argument 'x' lacks a leading '+';\n" +
        'when using an option to specify date(s), any non-option\n' +
        "argument must be a format string beginning with '+'\n" +
        "Try 'date --help' for more information.\n",
    ],
    [
      'date 010100002024 +%F',
      '',
      "date: extra operand '+%F'\nTry 'date --help' for more information.\n",
    ],
  ])('%s sets the clock', async (line, out, err) => {
    const ws = await makeWs()
    const io = await ws.shell(line)
    await ws.close()
    expect([io.stdoutText, io.stderrText, io.exitCode]).toEqual([out, err, 1])
  })

  it('renders now with the offset', async () => {
    const ws = await makeWs()
    const io = await ws.shell('date -u -Is')
    await ws.close()
    expect([io.stderrText, io.exitCode]).toEqual(['', 0])
    expect(io.stdoutText).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00\n$/)
  })
})
