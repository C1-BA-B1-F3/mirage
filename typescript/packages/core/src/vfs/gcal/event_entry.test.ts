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
import { NAME_MAX_BYTES } from '../../utils/sanitize.ts'
import {
  PRIMARY_DIR,
  eventTitle,
  makeCalendarDirname,
  makeEventFilename,
  parseEventFilename,
} from './event_entry.ts'

const EVENT_ID = 'la9i1t995acovthi3f761chla0'
const UTF8 = new TextEncoder()

function byteLength(value: string): number {
  return UTF8.encode(value).length
}

describe('gcal event entry naming', () => {
  it.each([
    ['PhD_Defense', null, `${EVENT_ID}__0900-1030_PhD_Defense.gcal.json`],
    ['A__B_C', null, `${EVENT_ID}__0900-1030_A__B_C.gcal.json`],
    ['PhD_Defense', '2026-08-11', `${EVENT_ID}__2026-08-11_0900-1030_PhD_Defense.gcal.json`],
  ])('leads with the id and round trips %s on %s', (title, day, name) => {
    expect(makeEventFilename(EVENT_ID, '0900-1030', title, day)).toBe(name)
    expect(parseEventFilename(name)).toEqual([EVENT_ID, day])
  })

  it.each([
    'notes.txt',
    'noseparator.gcal.json',
    `${EVENT_ID}__090.gcal.json`,
    `${EVENT_ID}__0900-1030x.gcal.json`,
    `${EVENT_ID}__2026-08-11_090.gcal.json`,
  ])('refuses %s, which has no time label', (name) => {
    expect(() => parseEventFilename(name)).toThrow()
  })

  it.each([
    ['ascii', 'a'.repeat(400), null],
    ['ascii', 'a'.repeat(400), '2026-08-11'],
    ['cjk', '会'.repeat(200), null],
    ['cjk', '会'.repeat(200), '2026-08-11'],
  ])('trims a long %s title by bytes to NAME_MAX (day %s)', (_kind, title, day) => {
    // 3 bytes per CJK character: a character-counted budget would overflow
    // NAME_MAX, the bug gdocs/gsheets/gslides had until sanitizeLabel grew a
    // byte budget.
    const name = makeEventFilename(EVENT_ID, '0900-1030', title, day)
    expect(byteLength(name)).toBeLessThanOrEqual(NAME_MAX_BYTES)
    expect(name).not.toContain('�')
    expect(parseEventFilename(name)).toEqual([EVENT_ID, day])
  })

  it('drops the title when a long id leaves no room', () => {
    // 234 is the widest id that still names an event: the title is squeezed
    // out and id + separators + suffix lands exactly on NAME_MAX.
    const longId = 'v'.repeat(234)
    const name = makeEventFilename(longId, '0900-1030', 'Some_Title')
    expect(name).toBe(`${longId}__0900-1030.gcal.json`)
    expect(byteLength(name)).toBe(NAME_MAX_BYTES)
  })

  it('keeps an id too long to name rather than truncating it', () => {
    // The title is what gives, never the id: a trimmed id would stop
    // addressing the event. Google's own ids are 26 chars, so this only
    // arises for a caller-supplied events.import id.
    const longId = 'v'.repeat(NAME_MAX_BYTES - 20)
    const name = makeEventFilename(longId, '0900-1030', 'Some Title')
    expect(byteLength(name)).toBeGreaterThan(NAME_MAX_BYTES)
    expect(parseEventFilename(name)).toEqual([longId, null])
  })

  it.each([
    ['Standup', false, 'Standup'],
    [null, false, 'untitled'],
    ['   ', false, 'untitled'],
    [null, true, 'busy'],
  ])('titles %s (free/busy %s) as %s', (summary, freeBusy, title) => {
    expect(eventTitle(summary, freeBusy)).toBe(title)
  })

  it.each([
    ['integ@example.com', 'integ@example.com', true, PRIMARY_DIR],
    [
      'US Holidays',
      'en.usa#holiday@group.v.calendar.google.com',
      false,
      'US_Holidays__en.usa#holiday@group.v.calendar.google.com',
    ],
  ])('names calendar %s by its alias or id', (summary, calId, primary, name) => {
    expect(makeCalendarDirname(summary, calId, primary)).toBe(name)
  })
})
