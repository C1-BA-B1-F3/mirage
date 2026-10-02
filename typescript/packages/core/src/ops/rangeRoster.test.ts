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
import * as boxIo from '../commands/builtin/box/io.ts'
import * as databricksVolumeIo from '../commands/builtin/databricks_volume/io.ts'
import * as difyIo from '../commands/builtin/dify/io.ts'
import * as discordIo from '../commands/builtin/discord/io.ts'
import * as dropboxIo from '../commands/builtin/dropbox/io.ts'
import * as gdriveIo from '../commands/builtin/gdrive/io.ts'
import * as onedriveIo from '../commands/builtin/onedrive/io.ts'
import * as s3Io from '../commands/builtin/s3/io.ts'
import * as sharepointIo from '../commands/builtin/sharepoint/io.ts'
import * as slackIo from '../commands/builtin/slack/io.ts'
import * as ramIo from '../commands/builtin/ram/io.ts'
import * as redisIo from '../commands/builtin/redis/io.ts'
import * as notionIo from '../commands/builtin/notion/io.ts'
import * as postgresIo from '../commands/builtin/postgres/io.ts'

// Every backend that takes the window itself instead of leaving it to the
// generic read-and-slice fallback. Most push it down to the store (one ranged
// GET rather than the whole object); the ones that render their content or
// already hold it in memory take the window right after building the bytes, so
// a windowed read is answered the same way everywhere. Losing an entry here is
// not a failure anywhere else: the fallback keeps the backend correct while it
// silently starts reading whole objects again. Python pins the same roster in
// tests/ops/test_read_range_roster.py.
const NATIVE = {
  box: boxIo.IO,
  databricks_volume: databricksVolumeIo.IO,
  dify: difyIo.IO,
  discord: discordIo.IO,
  ram: ramIo.IO,
  redis: redisIo.IO,
  dropbox: dropboxIo.IO,
  gdrive: gdriveIo.IO,
  onedrive: onedriveIo.IO,
  s3: s3Io.IO,
  sharepoint: sharepointIo.IO,
  slack: slackIo.IO,
}

// Left to the generic read-and-slice fallback.
const SLICED = { notion: notionIo.IO, postgres: postgresIo.IO }

describe('native read range roster', () => {
  it.each(Object.entries(NATIVE))('%s pushes the window down', (_name, io) => {
    expect(io.readRange).toBeDefined()
  })

  it.each(Object.entries(SLICED))('%s leaves the slot empty', (_name, io) => {
    expect(io.readRange).toBeUndefined()
  })
})
