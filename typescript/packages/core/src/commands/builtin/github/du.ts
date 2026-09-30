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

import type { GitHubAccessor } from '../../../accessor/github.ts'
import { size as githubDu, entries as githubDuAll } from '../../../core/github/du/index.ts'
import { resolveGlobOf } from '../generic_bind/index.ts'
import { withPathGuards, withPolicyGuard } from '../generic_bind/adapter.ts'
import { GITHUB_IO } from './io.ts'
import { ensureLiveTree } from '../../../core/github/tree.ts'
import { VFSName, type PathSpec } from '../../../types.ts'
import { command, type CommandFnResult, type CommandOpts } from '../../config.ts'
import { specOf } from '../../spec/builtins.ts'
import { metadataProvision } from './_provision.ts'
import { IOResult } from '../../../io/types.ts'
import { DEFAULT_MAX_DU_ENTRIES, runDu } from '../generic/du.ts'
import { WalkBudget, walkEntries, walkSize } from '../generic_bind/builders/du.ts'

const resolveGlob = resolveGlobOf(GITHUB_IO)

async function duCommand(
  accessor: GitHubAccessor,
  paths: PathSpec[],
  _texts: string[],
  opts: CommandOpts,
): Promise<CommandFnResult> {
  const idx = opts.index ?? undefined
  // Sizes come from accessor.tree, so the first callback brings it live,
  // after du has validated its flags: an invalid line must cost no fetch.
  // Once per line, so one du reads one tree.
  let probe: Promise<void> | undefined
  const live = (): Promise<void> =>
    (probe ??= ensureLiveTree(accessor, idx, opts.mountPrefix ?? ''))
  const budget = new WalkBudget(GITHUB_IO.maxDuEntries ?? DEFAULT_MAX_DU_ENTRIES)
  const out = await runDu(
    paths,
    opts,
    async (targets) => {
      await live()
      return resolveGlob(accessor, targets, idx)
    },
    async (p) => {
      await live()
      return GITHUB_IO.stat(accessor, p, idx)
    },
    // A truncated tree names only some paths and is never refetched, so it
    // is walked folder by folder, as a backend with no tree would be.
    async (p) => {
      await live()
      if (accessor.truncated)
        return walkSize(withPolicyGuard(withPathGuards(GITHUB_IO)), accessor, idx, budget, p)
      return githubDu(accessor, p, idx)
    },
    async (p) => {
      await live()
      if (accessor.truncated)
        return walkEntries(withPolicyGuard(withPathGuards(GITHUB_IO)), accessor, idx, budget, p)
      return githubDuAll(accessor, p, idx)
    },
    () => budget.hit,
    () => budget.unreadable,
    () => budget.directories,
  )
  return [out.stdout, new IOResult({ stderr: out.stderr, exitCode: out.exitCode })]
}

export const GITHUB_DU = command({
  name: 'du',
  vfs: VFSName.GITHUB,
  spec: specOf('du'),
  fn: duCommand,
  provision: metadataProvision,
})
