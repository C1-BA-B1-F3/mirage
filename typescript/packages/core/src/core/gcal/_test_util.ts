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

import { GCalAccessor } from '../../accessor/gcal.ts'
import { type JsonValue, PathSpec } from '../../types.ts'
import { type GCalConfig, normalizeGCalConfig } from '../../vfs/gcal/config.ts'
import { TokenManager } from '../google/client.ts'
import type { TimeRange } from '../time_range.ts'
import { eventSpan } from './day.ts'

export const HK = 'Asia/Hong_Kong'
const TODAY = '2026-08-11'

const PRIMARY: Record<string, JsonValue> = {
  id: 'integ@example.com',
  summary: 'Integ User',
  timeZone: HK,
  accessRole: 'owner',
  primary: true,
}
const TEAM: Record<string, JsonValue> = {
  id: 'team@group.calendar.google.com',
  summary: 'Engineering',
  timeZone: 'America/Los_Angeles',
  accessRole: 'reader',
}
const SHARED: Record<string, JsonValue> = {
  id: 'busy@group.calendar.google.com',
  summary: 'Exec',
  timeZone: HK,
  accessRole: 'freeBusyReader',
}

/** An events.list item: a `YYYY-MM-DD` pair is an all-day event. */
function event(id: string, summary: string, start: string, end: string): Record<string, JsonValue> {
  const key = start.length === 10 ? 'date' : 'dateTime'
  return {
    id,
    status: 'confirmed',
    summary,
    start: { [key]: start },
    end: { [key]: end },
    updated: '2026-08-01T00:00:00.000Z',
  }
}

export const EVENTS: readonly Record<string, JsonValue>[] = [
  event('aaaa1', 'PhD Defense', '2026-08-11T09:00:00+08:00', '2026-08-11T10:30:00+08:00'),
  event('bbbb2', 'Committee Meeting', '2026-08-11T15:00:00+08:00', '2026-08-11T16:00:00+08:00'),
  event('cccc3', 'Conference', '2026-08-10T09:00:00+08:00', '2026-08-13T17:00:00+08:00'),
  event('dddd4', 'Public Holiday', '2026-08-11', '2026-08-12'),
  event('eeee5', 'Last Year', '2025-01-05T09:00:00+08:00', '2025-01-05T10:00:00+08:00'),
]

/**
 * The Calendar API the gcal core calls, over `EVENTS`.
 *
 * Test files mock `./client.ts` with `CLIENT`, which delegates here, and
 * reset this one instance per test. It records every events.list window
 * and every deletion, so a test can pin how many requests a listing cost.
 */
class FakeCalendarApi {
  listed: [string, string | null, string][] = []
  deleted: [string, string][] = []

  reset(): void {
    this.listed = []
    this.deleted = []
  }

  listCalendars(minAccessRole?: string): Record<string, JsonValue>[] {
    const all = [PRIMARY, TEAM, SHARED]
    if (minAccessRole === undefined || minAccessRole === '') return all
    return all.filter((c) => c.accessRole === minAccessRole)
  }

  listEvents(
    calendarId: string,
    timeMin: string | null,
    timeMax: string,
    timeZone: string | undefined,
    scope: TimeRange | undefined,
  ): Record<string, JsonValue>[] {
    this.listed.push([calendarId, timeMin, timeMax])
    const lo = timeMin === null ? -Infinity : Date.parse(timeMin)
    const hi = Date.parse(timeMax)
    const out: Record<string, JsonValue>[] = []
    for (const item of EVENTS) {
      const span = eventSpan(item, timeZone ?? HK)
      if (span === null) continue
      // timeMin bounds the END and timeMax the START, both exclusive.
      if (span[1] <= lo || span[0] >= hi) continue
      if (scope?.start != null && span[1] <= scope.start * 1000) continue
      if (scope?.end != null && span[0] >= scope.end * 1000) continue
      if (calendarId === SHARED.id) {
        // What Google actually returns for a freeBusyReader role:
        // availability with no summary, description or location.
        const rest: Record<string, JsonValue> = {}
        for (const [k, v] of Object.entries(item)) {
          if (k !== 'summary' && k !== 'description' && k !== 'location') rest[k] = v
        }
        out.push(rest)
        continue
      }
      out.push(item)
    }
    return out
  }
}

export const API = new FakeCalendarApi()

export const CLIENT = {
  listCalendars: (_tm: unknown, minAccessRole?: string) =>
    Promise.resolve(API.listCalendars(minAccessRole)),
  listEvents: (
    _tm: unknown,
    calendarId: string,
    timeMin: string | null,
    timeMax: string,
    timeZone?: string,
    scope?: TimeRange,
  ) => Promise.resolve(API.listEvents(calendarId, timeMin, timeMax, timeZone, scope)),
  deleteEvent: (_tm: unknown, calendarId: string, eventId: string) => {
    API.deleted.push([calendarId, eventId])
    return Promise.resolve()
  },
}

/** A mount config against the fake, today pinned to `TODAY`. */
export function gcalConfig(overrides: Record<string, unknown> = {}): GCalConfig {
  return normalizeGCalConfig({
    client_id: 'cid',
    refresh_token: 'rt',
    today: TODAY,
    ...overrides,
  })
}

/** An accessor for `gcalConfig(overrides)`. */
export function makeAccessor(overrides: Record<string, unknown> = {}): GCalAccessor {
  const config = gcalConfig(overrides)
  return new GCalAccessor({ tokenManager: new TokenManager(config), config })
}

/** A mount-relative PathSpec, globbed when a pattern is given. */
export function spec(virtual: string, pattern?: string): PathSpec {
  const directory =
    pattern !== undefined ? virtual.slice(0, virtual.lastIndexOf('/')) || '/' : virtual
  return new PathSpec({
    virtual,
    directory,
    vfsPath: virtual.replace(/^\//, ''),
    ...(pattern !== undefined ? { pattern } : {}),
  })
}

/** The last segment of each listed path. */
export function names(paths: readonly string[]): string[] {
  return paths.map((p) => p.slice(p.lastIndexOf('/') + 1))
}
