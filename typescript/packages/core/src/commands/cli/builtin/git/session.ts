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

import type { FlagView } from '../../../spec/flag_view.ts'
import type { CLIDoors } from '../../types.ts'
import { discover, requireWorkTree } from './discover.ts'
import { NoWorkspaceError } from './errors.ts'
import { openRepo, type Repo } from './repo.ts'
import { startPoint } from './util.ts'

/**
 * Discover and open the repository a verb was invoked against.
 *
 * Every verb starts the same way: honor `-C`, walk up to the mount root looking
 * for a `.git`, then open the object database across the dispatcher. Kept in one
 * place so a new verb inherits the discovery rules rather than restating them.
 *
 * @param fl the leaf's flag bag, read for `-C`, `--git-dir` and `--work-tree`
 * @param doors the invocation's doors, one per state plane
 * @param workTree the verb reads or writes working files, so there must be a
 *   work tree to enter, as git's `NEED_WORK_TREE` asks
 */
export async function opened(fl: FlagView, doors: CLIDoors, workTree = false): Promise<Repo> {
  const dispatch = doors.dispatch
  const statPath = doors.statPath
  // The mount root comes from the name plane rather than a door of its own:
  // `ns.mounts.rootOf` is the same fact the command tier reads, and a second
  // field holding the same callable is a second thing to keep in step.
  const mounts = doors.ns?.mounts
  if (statPath === undefined || mounts === undefined || dispatch === undefined) {
    throw new NoWorkspaceError()
  }
  const chosen = fl.asStr('work_tree')
  const location = await discover(
    dispatch,
    statPath,
    (path: string) => mounts.rootOf(path),
    startPoint(fl),
    fl.asStr('git_dir'),
    chosen,
  )
  if (workTree) await requireWorkTree(dispatch, statPath, location, chosen !== undefined)
  return openRepo(dispatch, location)
}
