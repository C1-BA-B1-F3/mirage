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

import { searchResources } from '../../../vfs/search.ts'

import type { ChromaAccessor } from '../../../accessor/chroma.ts'

import { CHROMA_IO } from './io.ts'

import { IOResult } from '../../../io/types.ts'
import type { PathSpec } from '../../../types.ts'
import { VFSName } from '../../../types.ts'

import { command, type CommandFnResult, type CommandOpts } from '../../config.ts'
import { specOf } from '../../spec/builtins.ts'
import { defaultPaths } from '../utils/operands.ts'
import { FlagView } from '../../spec/flag_view.ts'

const ENC = new TextEncoder()

async function searchCommand(
  accessor: ChromaAccessor,
  paths: PathSpec[],
  texts: string[],
  opts: CommandOpts,
): Promise<CommandFnResult> {
  const query = texts[0]
  if (query === undefined || query === '') {
    return [null, new IOResult({ exitCode: 1, stderr: ENC.encode('search: query is required\n') })]
  }
  const fl = new FlagView(opts.flags, specOf('search'))
  const targets = defaultPaths(paths, opts.cwd, opts.mountPrefix ?? '')
  try {
    const out = await searchResources(
      CHROMA_IO.search,
      accessor,
      targets,
      { query, options: { top_k: fl.asInt('top_k') ?? 10 } },
      opts.index ?? undefined,
    )
    return [out, new IOResult()]
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    return [null, new IOResult({ exitCode: 1, stderr: ENC.encode(`${msg}\n`) })]
  }
}

export const CHROMA_SEARCH = command({
  name: 'chroma-query',
  vfs: VFSName.CHROMA,
  spec: specOf('search'),
  fn: searchCommand,
})
