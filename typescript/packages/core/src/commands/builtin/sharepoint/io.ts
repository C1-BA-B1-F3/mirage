import { VFSAdapter } from '../../../vfs/adapter.ts'
import type { SharePointAccessor } from '../../../accessor/sharepoint.ts'
import * as drive from '../../../core/sharepoint/index.ts'
import { type CommandIO, rangeOf } from '../generic_bind/index.ts'

export const SHAREPOINT_IO: CommandIO<SharePointAccessor> = new VFSAdapter<SharePointAccessor>({
  read: { readdir: drive.readdir, readBytes: drive.read, stat: drive.stat },
  native: {
    readRange: rangeOf(drive.read),
    readStream: drive.stream,
    exists: drive.exists,
    find: drive.find,
    du: { size: drive.du, entries: drive.duEntries },
  },
  writes: {
    write: drive.write,
    mkdir: drive.mkdir,
    unlink: drive.unlink,
    rmdir: drive.rmdir,
    rmR: drive.rmR,
    rename: drive.rename,
    copy: drive.copy,
    dirCopy: drive.copy,
    create: drive.create,
    truncate: drive.truncate,
  },
  isMounted: () => true,
  local: false,
}).toCommandIO()
