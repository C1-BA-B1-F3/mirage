import { searchResources } from '../../../vfs/search.ts'
import type { Mem0Accessor } from '../../../accessor/mem0.ts'

import { IOResult } from '../../../io/types.ts'
import { VFSName, type PathSpec } from '../../../types.ts'

import { command, type CommandFnResult, type CommandOpts } from '../../config.ts'
import { specOf } from '../../spec/builtins.ts'
import { metadataProvision } from '../generic_bind/provision.ts'

import { defaultPaths } from '../utils/operands.ts'
import { MEM0_IO } from './io.ts'
import { FlagView } from '../../spec/flag_view.ts'

const ENCODER = new TextEncoder()

async function searchCommand(
  accessor: Mem0Accessor,
  paths: PathSpec[],
  texts: string[],
  opts: CommandOpts,
): Promise<CommandFnResult> {
  const query = texts[0]
  if (query === undefined || query === '') {
    return [
      null,
      new IOResult({ exitCode: 2, stderr: ENCODER.encode('search: query is required\n') }),
    ]
  }
  const fl = new FlagView(opts.flags, specOf('search'))
  const method = fl.asStr('method') ?? 'semantic'
  if (method !== 'semantic') {
    return [
      null,
      new IOResult({
        exitCode: 1,
        stderr: ENCODER.encode("search: only the 'semantic' method is supported\n"),
      }),
    ]
  }
  const targets = defaultPaths(paths, opts.cwd, opts.mountPrefix ?? '')
  try {
    const out = await searchResources(
      MEM0_IO.search,
      accessor,
      targets,
      {
        query,
        options: {
          top_k: fl.asInt('top_k') ?? accessor.config.defaultSearchLimit,
          method: fl.asStr('method') ?? 'semantic',
          threshold: fl.asFloat('threshold') ?? 0,
        },
      },
      opts.index ?? undefined,
    )
    return [out, new IOResult()]
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    return [null, new IOResult({ exitCode: 1, stderr: ENCODER.encode(`${message}\n`) })]
  }
}

export const MEM0_SEARCH = command({
  name: 'search',
  vfs: VFSName.MEM0,
  spec: specOf('search'),
  fn: searchCommand,
  provision: metadataProvision,
})
