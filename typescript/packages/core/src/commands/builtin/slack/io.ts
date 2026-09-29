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

import { VFSAdapter } from '../../../vfs/adapter.ts'

import type { SlackAccessor } from '../../../accessor/slack.ts'
import { read as slackRead, readRange as slackReadRange } from '../../../core/slack/read.ts'
import { DU_MAX_ENTRIES } from '../../../core/slack/constants.ts'
import { readdir as slackReaddir } from '../../../core/slack/readdir.ts'
import { stat as slackStat } from '../../../core/slack/stat.ts'
import { type CommandIO, rangeOf } from '../generic_bind/index.ts'

export const SLACK_IO: CommandIO<SlackAccessor> = new VFSAdapter<SlackAccessor>({
  read: { readdir: slackReaddir, readBytes: slackRead, stat: slackStat },
  native: {
    readRange: rangeOf(slackReadRange),
  },
  isMounted: () => true,
  local: false,
  maxDuEntries: DU_MAX_ENTRIES,
}).toCommandIO()
