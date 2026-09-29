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

import { VFSAdapter } from '@struktoai/mirage-core/vfs/adapter'

import type { IndexCacheStore } from '@struktoai/mirage-core/cache/index/store'
import type { CommandIO } from '@struktoai/mirage-core/commands/builtin/generic_bind/index'
import type { PathSpec } from '@struktoai/mirage-core/types'
import type { EmailAccessor } from '../../../accessor/email.ts'
import { read as emailRead } from '../../../core/email/read.ts'
import { readdir as emailReaddir } from '../../../core/email/readdir.ts'
import { stat as emailStat } from '../../../core/email/stat.ts'

async function* emailReadStream(
  accessor: EmailAccessor,
  path: PathSpec,
  index?: IndexCacheStore,
): AsyncIterable<Uint8Array> {
  yield await emailRead(accessor, path, index)
}

export const EMAIL_IO: CommandIO<EmailAccessor> = new VFSAdapter<EmailAccessor>({
  read: { readdir: emailReaddir, readBytes: emailRead, stat: emailStat },
  native: { readStream: emailReadStream },
  isMounted: () => true,
  local: false,
}).toCommandIO()
