import { VFSAdapter } from '../../../vfs/adapter.ts'
import type { WandbAccessor } from '../../../accessor/wandb.ts'
import { read, readStream } from '../../../core/wandb/read.ts'
import { readdir } from '../../../core/wandb/readdir.ts'
import { stat } from '../../../core/wandb/stat.ts'
import type { CommandIO } from '../generic_bind/index.ts'
export const WANDB_IO: CommandIO<WandbAccessor> = new VFSAdapter<WandbAccessor>({
  read: { readdir, readBytes: read, stat },
  native: { readStream },
  isMounted: () => true,
  local: false,
  maxDuEntries: 1000,
}).toCommandIO()
