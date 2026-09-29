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

import type { BinAccessor } from '../../../accessor/bin.ts'
import { read as binRead } from '../../../core/bin/read.ts'
import { readdir as binReaddir } from '../../../core/bin/readdir.ts'
import { stat as binStat } from '../../../core/bin/stat.ts'
import type { CommandIO } from '../generic_bind/index.ts'

// The view is read-only (the lookup owns what is there), so only the read
// trio is wired. There is no native streaming read, so the stream yields
// the whole rendered stub.
export const BIN_IO: CommandIO<BinAccessor> = {
  readdir: binReaddir,
  readBytes: binRead,
  readStream: async function* (accessor, path) {
    yield await binRead(accessor, path)
  },
  stat: binStat,
  isMounted: () => true,
  local: false,
}
