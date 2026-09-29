import { searchResource, searchMany } from '../../../core/mem0/search.ts'
import { VFSAdapter } from '../../../vfs/adapter.ts'
import type { Mem0Accessor } from '../../../accessor/mem0.ts'
import { read, readStream } from '../../../core/mem0/read.ts'
import { readdir } from '../../../core/mem0/readdir.ts'
import { stat } from '../../../core/mem0/stat.ts'
import type { CommandIO } from '../generic_bind/index.ts'

export const MEM0_IO: CommandIO<Mem0Accessor> = new VFSAdapter<Mem0Accessor>({
  search: { search: searchResource, searchMany },
  read: { readdir, readBytes: read, stat },
  native: { readStream },
  isMounted: () => true,
  local: false,
}).toCommandIO()
