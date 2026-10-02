# ========= Copyright 2026 @ Strukto.AI All Rights Reserved. =========
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ========= Copyright 2026 @ Strukto.AI All Rights Reserved. =========

PROMPT = """Google Calendar is mounted as one directory per calendar, one
directory per local day, and one JSON file per event.

    /<mount>/primary/calendar.json
    /<mount>/primary/2026-08-11/<eventId>__0900-1030_Team_Standup.gcal.json
    /<mount>/Engineering__team@group.calendar.google.com/2026-08-11/...

Reading the tree:

- `ls <mount>/` lists the calendars. The primary one is always spelled
  `primary`; every other directory ends in `__<calendarId>`.
- `ls <mount>/primary/` lists days with events from all available history
  through today +90 days unless end_time is configured. start_time/end_time
  restrict this mount, including direct paths, date globs and event reads.
  A date glob such as `ls <mount>/primary/2027-03-*` selects its own
  listing range within that scope, beyond the default future horizon.
- A well-formed date inside the configured scope is a directory even when
  it holds no events. Dates outside the scope are absent.
- A file name is `<eventId>__<HHMM-HHMM>_<Title>.gcal.json`. The times are
  clamped to that day, so an event running through it reads `0000-2400`.
  A multi-day event appears under every day it covers.
- `cat` an event for the unmodified Calendar API payload, including
  attendees, description, location and the original start/end with offsets.
- `calendar.json` carries the calendar's accessRole and, in
  `bucketTimeZone`, the zone the day directories are bucketed in. That zone
  is mount-wide, so every calendar's `2026-08-11/` covers the same 24 hours.
- On a calendar shared as free/busy only, Google returns no titles at all,
  so events render as `busy`.

Acting on it:

- `rm` an event file to delete that event.
- Everything else goes through the `gws calendar` CLI, which takes the ids
  the tree renders:
  `gws calendar events insert --params '{"calendarId":"primary"}' --json ...`
  `gws calendar events patch --params '{"calendarId":"primary","eventId":"..."}'`
  `gws calendar freebusy query --json '{"timeMin":...,"timeMax":...,"items":[{"id":"primary"}]}'`
- A written event must carry an explicit UTC offset or timeZone; an
  ambiguous local time is not interpreted for you.
"""

BUCKET_PROMPT = """
  Buckets: bucket_days={days}, so each date directory holds {days} days
  instead of one, named by its first and last day (`2026-08-10--2026-08-16/`)
  on a fixed grid where 7-day buckets run Monday to Sunday. A bucket on the
  grid is a directory even when it holds no events; a bare date or a span
  off the grid is not. File names carry their day,
  `<eventId>__<YYYY-MM-DD>_<HHMM-HHMM>_<Title>.gcal.json`, and an event
  appears once for each day of the bucket it covers."""

WRITE_PROMPT = """Deleting an event file removes it from the calendar for
every attendee. Creating and editing events goes through `gws calendar`.
"""
