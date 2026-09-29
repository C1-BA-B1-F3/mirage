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

import { IOResult } from '../../../../io/types.ts'
import type { CommandFnResult } from '../../../config.ts'
import { FlagView } from '../../../spec/flag_view.ts'
import type { CLIInvocation } from '../../types.ts'
import { GitError } from './errors.ts'
import {
  needsDecorations,
  oneline,
  presetBlock,
  renderTemplate,
  type CommitFacts,
  type Decorations,
  type LogFormat,
} from './format.ts'
import { decorations, prettyFormat } from './history.ts'
import {
  joinOutput,
  commitOutput,
  parseDiffFlags,
  renamesEnabled,
  type DiffFlags,
} from './diff_output.ts'
import { commitFacts, configBool, opened } from './repo.ts'
import { resolveCommit } from './revparse.ts'
import { checkOperands, escaped, fatal, revisionArg } from './util.ts'
import { encodeText } from '../../../../shell/bytes.ts'

/**
 * The parsed shape of a `git show` invocation.
 *
 * `--no-ext-diff` is accepted but carries no field: there are no external
 * diff drivers here, so it changes nothing by construction.
 */
interface ShowFlags {
  readonly diff: DiffFlags
  readonly pretty: LogFormat
  readonly date: string
}

/** Read the raw show flag kwargs into a frozen struct. */
function parseShowFlags(fl: FlagView, defaultRenames = true, quotePathFully = true): ShowFlags {
  const pretty = prettyFormat(fl)
  return {
    date: fl.asStr('date') ?? 'default',
    diff: parseDiffFlags(fl, true, 'dense-combined', true, defaultRenames, quotePathFully),
    pretty,
  }
}

/**
 * The commit header in the requested format.
 *
 * `format:` is a separator, so a single commit prints with no trailing
 * newline at all; `tformat:` terminates the entry even when it renders
 * empty, except that an empty template prints nothing, matching
 * `log --format=`. Pinned against git 2.37 and 2.54.
 */
function header(
  commit: CommitFacts,
  flags: ShowFlags,
  width: number,
  decor: Decorations | null,
): string {
  const fmt = flags.pretty
  if (fmt.kind === 'oneline') return `${oneline(commit, width)}\n`
  if (fmt.kind === 'format' || fmt.kind === 'tformat') {
    const text = renderTemplate(fmt.template ?? '', commit, width, decor, flags.date)
    if (fmt.kind === 'tformat') {
      return fmt.template === null || fmt.template === '' ? '' : `${text}\n`
    }
    return text
  }
  return `${presetBlock(commit, fmt.kind, width, flags.date).join('\n')}\n`
}

/** Show one commit: its log entry, then its diff against its parent. */
export async function show(inv: CLIInvocation): Promise<CommandFnResult> {
  const doors = inv.doors ?? {}
  const texts = [...inv.texts]
  const fl = new FlagView(inv.flags)
  try {
    checkOperands(texts, undefined, escaped(inv.argv))
    const repo = await opened(fl, doors)
    const parsed = parseShowFlags(
      fl,
      await renamesEnabled(repo),
      await configBool(repo, 'core.quotepath', true),
    )
    const oid = await resolveCommit(repo, revisionArg(texts))
    const facts = await commitFacts(repo, oid)
    const decor = needsDecorations(parsed.pretty) ? await decorations(repo) : null
    const head = header(facts, parsed, repo.abbrev, decor)
    const bodies = await commitOutput(repo, facts, parsed.diff)
    return [
      encodeText(
        joinOutput(
          facts,
          head,
          bodies,
          parsed.pretty.kind,
          repo.abbrev,
          parsed.diff,
          parsed.diff.summary && !parsed.diff.noPatch,
        ),
      ),
      new IOResult(),
    ]
  } catch (err) {
    if (err instanceof GitError) return fatal(err)
    throw err
  }
}

export async function diffTree(inv: CLIInvocation): Promise<CommandFnResult> {
  const fl = new FlagView(inv.flags)
  try {
    const repo = await opened(fl, inv.doors ?? {})
    const commit = await commitFacts(repo, await resolveCommit(repo, inv.texts[0] ?? 'HEAD'))
    const bodies = await commitOutput(
      repo,
      commit,
      parseDiffFlags(fl, false, 'off', false, true, await configBool(repo, 'core.quotepath', true)),
      fl.asBool('r'),
      false,
    )
    const out = bodies
      .map((body) => (fl.asBool('no_commit_id') ? '' : commit.oid + '\n') + body)
      .join('')
    return [encodeText(out), new IOResult()]
  } catch (err) {
    if (err instanceof GitError) return fatal(err)
    throw err
  }
}
