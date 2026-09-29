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

import { ContentType, FileType } from '../../types.ts'
import { entryStat, makeStat } from '../hierarchy/stat.ts'
import { readdir } from './readdir.ts'
import { detectScope } from './scope.ts'

export const stat = makeStat(detectScope, readdir, {
  entryStats: {
    base: entryStat('base_id', FileType.DIRECTORY),
    base_json: entryStat('base_id', ContentType.JSON),
    table: entryStat('table_id', FileType.DIRECTORY),
    table_json: entryStat('table_id', ContentType.JSON),
    records: entryStat('table_id', ContentType.TEXT),
    views: entryStat('table_id', FileType.DIRECTORY),
    view: entryStat('view_id', ContentType.TEXT),
  },
})
