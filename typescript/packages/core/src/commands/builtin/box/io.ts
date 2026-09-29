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

import { VFSAdapter } from '../../../vfs/adapter.ts'

import type { BoxAccessor } from '../../../accessor/box.ts'
import { size as boxDu, entries as boxDuAll } from '../../../core/box/du/index.ts'
import { read as boxRead, stream as boxStream } from '../../../core/box/read.ts'
import { readdir as boxReaddir } from '../../../core/box/readdir.ts'
import { stat as boxStat } from '../../../core/box/stat.ts'
import {
  copy as boxCopy,
  create as boxCreate,
  exists as boxExists,
  mkdir as boxMkdir,
  rename as boxRename,
  rmR as boxRmR,
  rmdir as boxRmdir,
  truncate as boxTruncate,
  unlink as boxUnlink,
  write as boxWrite,
} from '../../../core/box/write.ts'
import { type CommandIO, rangeOf } from '../generic_bind/index.ts'

export const BOX_IO: CommandIO<BoxAccessor> = new VFSAdapter<BoxAccessor>({
  read: { readdir: boxReaddir, readBytes: boxRead, stat: boxStat },
  native: {
    readRange: rangeOf(boxRead),
    readStream: boxStream,
    du: { size: boxDu, entries: boxDuAll },
    exists: boxExists,
  },
  writes: {
    write: boxWrite,
    mkdir: boxMkdir,
    unlink: boxUnlink,
    rmdir: boxRmdir,
    rmR: boxRmR,
    rename: boxRename,
    copy: boxCopy,
    dirCopy: boxCopy,
    create: boxCreate,
    truncate: boxTruncate,
  },
  isMounted: () => true,
  local: false,
}).toCommandIO()
