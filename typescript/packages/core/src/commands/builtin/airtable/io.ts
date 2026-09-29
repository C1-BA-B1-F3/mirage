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

import type { AirtableAccessor } from '../../../accessor/airtable.ts'
import { read as airtableRead } from '../../../core/airtable/read.ts'
import { readdir as airtableReaddir } from '../../../core/airtable/readdir.ts'
import { stat as airtableStat } from '../../../core/airtable/stat.ts'
import type { CommandIO } from '../generic_bind/index.ts'
import { streamFromBytes } from '../utils/wrap.ts'

// Airtable is read-only through the file surface: no write op is wired, so
// the byte-mutation commands are absent. head pushes its line count into
// maxRecords (kept bespoke); everything else runs generic over the rendered
// files.
export const AIRTABLE_IO: CommandIO<AirtableAccessor> = {
  readdir: airtableReaddir,
  readBytes: airtableRead,
  streamsBytes: true,
  readStream: (a, p, i) => streamFromBytes(airtableRead, a, p, i),
  stat: airtableStat,
  isMounted: () => true,
  local: false,
}
