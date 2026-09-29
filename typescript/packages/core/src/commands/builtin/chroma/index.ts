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

import type { ChromaAccessor } from '../../../accessor/chroma.ts'
import { VFSName } from '../../../types.ts'
import type { RegisteredCommand } from '../../config.ts'
import { resolveGlobOf } from '../generic_bind/adapter.ts'
import { makeGenericCommands } from '../generic_bind/index.ts'
import { withDefaultProvisions } from '../generic_bind/provision.ts'
import { CHROMA_FIND } from './find.ts'
import { CHROMA_IO } from './io.ts'
import { CHROMA_SEARCH } from './search.ts'

const CHROMA_OVERRIDES = new Set(['find'])

export const CHROMA_COMMANDS: readonly RegisteredCommand[] = [
  ...makeGenericCommands<ChromaAccessor>(VFSName.CHROMA, CHROMA_IO, {
    overrides: CHROMA_OVERRIDES,
  }),
  ...withDefaultProvisions(
    [...CHROMA_FIND, ...CHROMA_SEARCH],
    CHROMA_IO.stat,
    resolveGlobOf(CHROMA_IO),
    CHROMA_IO.readdir,
  ),
]
