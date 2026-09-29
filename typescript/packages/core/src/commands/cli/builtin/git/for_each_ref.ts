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

import git from 'isomorphic-git'
import { IOResult } from '../../../../io/types.ts'
import { fnmatch } from '../../../../utils/fnmatch.ts'
import { compareCodePoints } from '../../../../utils/sort.ts'
import type { CommandFnResult } from '../../../config.ts'
import { FlagView } from '../../../spec/flag_view.ts'
import type { CLIInvocation } from '../../types.ts'
import { GitError } from './errors.ts'
import { loadRefs } from './refs.ts'
import { opened, repoArgs } from './repo.ts'
import { resolveObject } from './revparse.ts'
import { fatal } from './util.ts'

const DEFAULT_FORMAT = '%(objectname) %(objecttype)\t%(refname)'
const PLACEHOLDER = /%\(([^)]+)\)|%([0-9a-fA-F]{2})/g
const SHORT_PREFIX = /^refs\/(heads|tags|remotes)\//

/** Match a pattern against a ref one component at a time. */
function pathMatch(parts: readonly string[], name: readonly string[]): boolean {
  const [head, ...rest] = parts
  if (head === undefined) return name.length === 0
  if (head === '**') {
    for (let i = 0; i <= name.length; i++) if (pathMatch(rest, name.slice(i))) return true
    return false
  }
  const [first] = name
  return first !== undefined && fnmatch(first, head) && pathMatch(rest, name.slice(1))
}

/**
 * Whether a ref is one of the patterns', as `match_name_as_path`.
 *
 * A pattern selects a ref it spells in full or up to a `/`, or one it matches
 * as a `WM_PATHNAME` glob: `*` stops at a `/`, so `refs/*` selects nothing
 * while `refs/*\/*` and `refs/**` select every branch (git 2.47.3 and 2.50.1).
 */
export function refSelected(name: string, patterns: readonly string[]): boolean {
  if (!patterns.length) return true
  const components = name.split('/')
  return patterns.some(
    (pattern) =>
      (name.startsWith(pattern) &&
        (name.length === pattern.length ||
          name[pattern.length] === '/' ||
          pattern.endsWith('/'))) ||
      pathMatch(pattern.split('/'), components),
  )
}

/** Format the repository's references, including packed refs. */
export async function forEachRef(inv: CLIInvocation): Promise<CommandFnResult> {
  const fl = new FlagView(inv.flags)
  try {
    const count = fl.asInt('count') ?? 0
    if (count < 0) throw new GitError(`invalid --count argument: ${String(count)}`)
    const repo = await opened(fl, inv.doors ?? {})
    const refs = await loadRefs(repo.dispatch, repo.location.gitdir, repo.location.commondir)
    const template = fl.asStr('format') ?? DEFAULT_FORMAT
    const rows: string[] = []
    const names = [...refs.keys()].filter((ref) => ref.startsWith('refs/')).sort(compareCodePoints)
    for (const name of names) {
      if (!refSelected(name, inv.texts)) continue
      const oid = await git.resolveRef({ ...repoArgs(repo), ref: name })
      const obj = await resolveObject(repo, oid)
      let message = ''
      if (obj.type === 'commit')
        message = (await git.readCommit({ ...repoArgs(repo), oid })).commit.message
      if (obj.type === 'tag') message = (await git.readTag({ ...repoArgs(repo), oid })).tag.message
      const atoms: Record<string, string> = {
        refname: name,
        'refname:short': name.replace(SHORT_PREFIX, ''),
        objectname: oid,
        'objectname:short': oid.slice(0, repo.abbrev),
        objecttype: obj.type,
        subject: (message.split('\n\n')[0] ?? '').trimEnd().replaceAll('\n', ' '),
        contents: message,
      }
      rows.push(
        template.replace(
          PLACEHOLDER,
          (_match, atom: string | undefined, hex: string | undefined) => {
            if (atom === undefined) return String.fromCharCode(parseInt(hex ?? '0', 16))
            if (!Object.hasOwn(atoms, atom)) throw new GitError(`unknown field name: ${atom}`)
            return atoms[atom] ?? ''
          },
        ) + '\n',
      )
      if (count && rows.length >= count) break
    }
    return [new TextEncoder().encode(rows.join('')), new IOResult()]
  } catch (err) {
    if (err instanceof GitError) return fatal(err)
    throw err
  }
}
