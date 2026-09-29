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

import type { DiscordAccessor } from '../../../accessor/discord.ts'
import { read as discordRead, readRange as discordReadRange } from '../../../core/discord/read.ts'
import { readdir as discordReaddir } from '../../../core/discord/readdir.ts'
import { stat as discordStat } from '../../../core/discord/stat.ts'
import { type CommandIO, rangeOf } from '../generic_bind/index.ts'

export const DISCORD_IO: CommandIO<DiscordAccessor> = new VFSAdapter<DiscordAccessor>({
  read: { readdir: discordReaddir, readBytes: discordRead, stat: discordStat },
  native: {
    readRange: rangeOf(discordReadRange),
  },
  isMounted: () => true,
  local: false,
}).toCommandIO()
