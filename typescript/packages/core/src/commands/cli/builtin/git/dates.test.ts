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
import { resolveTz, UTC_ZONE } from '../../../../utils/timezone.ts'
import { dateClock, parseDateMode, relativeDate, showDate } from './dates.ts'
import { DateFormatColonError, UnknownDateFormatError } from './errors.ts'
import { DateKind, type DateMode } from './types.ts'

const BASE: DateMode = { kind: DateKind.NORMAL, local: false, strftime: '', now: 0, zone: null }
const CLOCK: DateMode = { ...BASE, now: 1768561800, zone: UTC_ZONE }

describe('showDate', () => {
  it.each([
    [330, '16:40 +0530'],
    [-420, '04:10 -0700'],
  ])('keeps the instant and percent escapes when formatting epoch at offset %i', (offset, wall) => {
    const mode = parseDateMode('format:%s %%s %%%s %H:%M %z', CLOCK)
    expect(showDate(1768561800, offset, mode)).toBe(`1768561800 %s %1768561800 ${wall}`)
  })

  it('keeps the instant when formatting a local epoch', () => {
    const clock = dateClock({ TZ: 'Asia/Kolkata' })
    const mode = parseDateMode('format-local:%s %H:%M %z', clock)
    expect(showDate(1768561800, -420, mode)).toBe('1768561800 16:40 +0530')
  })

  it("matches git's default format, the day unpadded", () => {
    expect(showDate(1768561800, 0, BASE)).toBe('Fri Jan 16 11:10:00 2026 +0000')
    expect(showDate(1767603900, 0, BASE)).toBe('Mon Jan 5 09:05:00 2026 +0000')
  })

  it("renders in the author's own offset", () => {
    expect(showDate(1768561800, 8 * 60, BASE)).toBe('Fri Jan 16 19:10:00 2026 +0800')
    expect(showDate(1768561800, -7 * 60, BASE)).toBe('Fri Jan 16 04:10:00 2026 -0700')
  })

  it.each([
    ['iso', '2026-01-16 16:40:00 +0530'],
    ['iso8601', '2026-01-16 16:40:00 +0530'],
    ['iso-strict', '2026-01-16T16:40:00+05:30'],
    ['iso8601-strict', '2026-01-16T16:40:00+05:30'],
    ['rfc', 'Fri, 16 Jan 2026 16:40:00 +0530'],
    ['rfc2822', 'Fri, 16 Jan 2026 16:40:00 +0530'],
    ['short', '2026-01-16'],
    ['raw', '1768561800 +0530'],
    ['unix', '1768561800'],
    ['default', 'Fri Jan 16 16:40:00 2026 +0530'],
    ['auto:iso', 'Fri Jan 16 16:40:00 2026 +0530'],
    ['local', 'Fri Jan 16 11:10:00 2026'],
    ['iso-local', '2026-01-16 11:10:00 +0000'],
    ['format:%Y/%m/%d %z [%Z]', '2026/01/16 +0530 []'],
    ['format-local:%H:%M %Z', '11:10 UTC'],
    ['format:', ''],
  ])('renders the style %s', (value, expected) => {
    expect(showDate(1768561800, 330, parseDateMode(value, CLOCK))).toBe(expected)
  })

  it('names UTC as Z in the strict ISO style', () => {
    expect(showDate(1768561800, 0, parseDateMode('iso-strict', CLOCK))).toBe('2026-01-16T11:10:00Z')
  })

  it.each([
    [1768561800 + 3600, '60 minutes ago'],
    [1768561800 + 3 * 86400, 'Fri 16:40 +0530'],
    [1768561800 + 20 * 86400, 'Fri Jan 16 16:40'],
    [1768561800 + 400 * 86400, 'Jan 16 2026'],
  ])('hides what the reader knows in the human style, now %i', (now, expected) => {
    const mode = { ...BASE, kind: DateKind.HUMAN, now, zone: UTC_ZONE }
    expect(showDate(1768561800, 330, mode)).toBe(expected)
  })

  it("hides the reader's own offset in the human style", () => {
    const mode = {
      ...BASE,
      kind: DateKind.HUMAN,
      now: 1768561800 + 3 * 86400,
      zone: resolveTz('Asia/Kolkata'),
    }
    expect(showDate(1768561800, 330, mode)).toBe('Fri 16:40')
  })
})

describe('parseDateMode', () => {
  it.each(['bogus', 'iso8601x', 'local-bogus'])('refuses %s whole', (value) => {
    expect(() => parseDateMode(value, CLOCK)).toThrow(UnknownDateFormatError)
    expect(() => parseDateMode(value, CLOCK)).toThrow(`unknown date format ${value}`)
  })

  it('needs the colon after format', () => {
    expect(() => parseDateMode('format', CLOCK)).toThrow(DateFormatColonError)
    expect(() => parseDateMode('format', CLOCK)).toThrow(
      'date format missing colon separator: format',
    )
  })
})

it.each([
  [-5, 'in the future'],
  [0, '0 seconds ago'],
  [1, '1 second ago'],
  [89, '89 seconds ago'],
  [90, '2 minutes ago'],
  [5369, '89 minutes ago'],
  [5399, '2 hours ago'],
  [36 * 3600, '2 days ago'],
  [14 * 86400, '2 weeks ago'],
  [70 * 86400, '2 months ago'],
  [365 * 86400, '1 year ago'],
  [400 * 86400, '1 year, 1 month ago'],
  [800 * 86400, '2 years, 2 months ago'],
  [1825 * 86400, '5 years ago'],
])('rounds a relative date %i seconds back as git does', (seconds, expected) => {
  expect(relativeDate(1768561800 - seconds, 1768561800)).toBe(expected)
})

it("reads git's test clock and TZ", () => {
  const clock = dateClock({ GIT_TEST_DATE_NOW: '1234 rest', TZ: 'UTC' })
  expect(clock.now).toBe(1234)
  expect(clock.zone).not.toBeNull()
  expect(dateClock({ GIT_TEST_DATE_NOW: 'x' }).now).toBe(0)
})
