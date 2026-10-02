import type { Mem0Accessor } from '../../../accessor/mem0.ts'
import { VFSName } from '../../../types.ts'
import type { RegisteredCommand } from '../../config.ts'
import { makeGenericCommands } from '../generic_bind/index.ts'
import { IO } from './io.ts'
import { MEM0_SEARCH } from './search.ts'

export const MEM0_COMMANDS: readonly RegisteredCommand[] = [
  ...makeGenericCommands<Mem0Accessor>(VFSName.MEM0, IO),
  ...MEM0_SEARCH,
]
