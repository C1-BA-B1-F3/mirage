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

import { commentsFor, commentsText } from './issue.ts'
import { FlagView } from '../../../spec/flag_view.ts'
import type { CommandFnResult } from '../../../config.ts'
import type { CLIInvocation } from '../../types.ts'
import {
  commentPull,
  createPull,
  diffPull,
  editPull,
  getPull,
  listPulls,
  mergePull,
  pullChecks,
} from '../../../../core/github/pull.ts'
import {
  bodyValue,
  camel,
  ghTransport,
  repoFor,
  repoNumber,
  textOut,
  textValue,
  typedOut,
} from './accessor.ts'

export const PR_FIELDS = [
  'additions',
  'author',
  'baseRefName',
  'body',
  'changedFiles',
  'closed',
  'createdAt',
  'deletions',
  'headRefName',
  'headRefOid',
  'isDraft',
  'labels',
  'mergeable',
  'mergedAt',
  'number',
  'state',
  'title',
  'updatedAt',
  'url',
] as const
const CHECK_FIELDS = [
  'bucket',
  'completedAt',
  'description',
  'event',
  'link',
  'name',
  'startedAt',
  'state',
  'workflow',
] as const

const BUCKETS: Record<string, string> = {
  success: 'pass',
  neutral: 'skipping',
  skipped: 'skipping',
  action_required: 'fail',
  error: 'fail',
  failure: 'fail',
  timed_out: 'fail',
  cancelled: 'cancel',
}

function pull(value: unknown): Record<string, unknown> {
  const row = camel(value)
  const result = row !== null && typeof row === 'object' ? (row as Record<string, unknown>) : {}
  const base = result.base as Record<string, unknown> | undefined
  const head = result.head as Record<string, unknown> | undefined
  if (base !== undefined) result.baseRefName = base.ref
  if (head !== undefined) {
    result.headRefName = head.ref
    result.headRefOid = head.sha
  }
  delete result.base
  delete result.head
  if ('draft' in result) {
    result.isDraft = result.draft
    delete result.draft
  }
  result.closed = textValue(result.state).toLowerCase() === 'closed'
  return result
}

function listText(rows: Record<string, unknown>[]): string {
  return rows
    .map(
      (row) =>
        `${textValue(row.number)}\t${textValue(row.state).toUpperCase()}\t${textValue(row.title)}\t${textValue(row.headRefName)}\n`,
    )
    .join('')
}

function viewText(row: Record<string, unknown>): string {
  const author = row.author as { login?: unknown } | undefined
  return `title:\t${textValue(row.title)}\nstate:\t${textValue(row.state).toUpperCase()}\nauthor:\t${textValue(author?.login)}\nbase:\t${textValue(row.baseRefName)}\nhead:\t${textValue(row.headRefName)}\n--\n${textValue(row.body)}\n`
}

function target(inv: CLIInvocation, fl: FlagView) {
  return repoNumber(inv, fl, inv.texts[0], 'pull request', 'pull')
}

export async function listCmd(inv: CLIInvocation): Promise<CommandFnResult> {
  const fl = new FlagView(inv.flags)
  const wanted = fl.asStr('state') ?? 'open'
  const params: Record<string, string> = { state: wanted === 'merged' ? 'closed' : wanted }
  const base = fl.asStr('base')
  const head = fl.asStr('head')
  if (base !== undefined) params.base = base
  if (head !== undefined) params.head = head
  const values = await listPulls(
    ghTransport(inv.config),
    repoFor(inv, fl),
    params,
    fl.asInt('limit') ?? 30,
    wanted === 'merged'
      ? (row) => row.merged_at !== null && row.merged_at !== undefined
      : undefined,
  )
  const rows = values.map(pull)
  return typedOut(rows, fl, listText(rows), PR_FIELDS)
}

export async function viewCmd(inv: CLIInvocation): Promise<CommandFnResult> {
  const fl = new FlagView(inv.flags)
  const [ref, number] = target(inv, fl)
  const row = pull(await getPull(ghTransport(inv.config), ref, number))
  const comments = await commentsFor(inv, fl, ref, number)
  if (comments !== null) row.comments = comments
  return typedOut(row, fl, fl.asBool('comments') ? commentsText(comments ?? []) : viewText(row), [
    ...PR_FIELDS,
    'comments',
  ])
}

export async function createCmd(inv: CLIInvocation): Promise<CommandFnResult> {
  const fl = new FlagView(inv.flags)
  const title = fl.asStr('title')
  const head = fl.asStr('head')
  const base = fl.asStr('base')
  const missing = [
    ['title', title],
    ['head', head],
    ['base', base],
  ].find(([, value]) => value === undefined || value === '')
  if (missing !== undefined)
    throw new Error(`--${String(missing[0])} is required in noninteractive mode`)
  const body = {
    title: title ?? '',
    head: head ?? '',
    base: base ?? '',
    body: (await bodyValue(inv, fl, { required: true })) ?? '',
    draft: fl.asBool('draft'),
    maintainer_can_modify: !fl.asBool('no_maintainer_edit'),
  }
  const created = pull(await createPull(ghTransport(inv.config), repoFor(inv, fl), body))
  return textOut(`${textValue(created.url)}\n`)
}

export async function editCmd(inv: CLIInvocation): Promise<CommandFnResult> {
  const fl = new FlagView(inv.flags)
  const body: Record<string, unknown> = {}
  const title = fl.asStr('title')
  const base = fl.asStr('base')
  const text = await bodyValue(inv, fl)
  if (title !== undefined) body.title = title
  if (base !== undefined) body.base = base
  if (text !== undefined) body.body = text
  if (Object.keys(body).length === 0) throw new Error('no pull request fields to edit')
  const [ref, number] = target(inv, fl)
  const edited = pull(await editPull(ghTransport(inv.config), ref, number, body))
  return textOut(`${textValue(edited.url)}\n`)
}

export async function mergeCmd(inv: CLIInvocation): Promise<CommandFnResult> {
  const fl = new FlagView(inv.flags)
  const methods = ['merge', 'rebase', 'squash'].filter((name) => fl.asBool(name))
  if (methods.length > 1) throw new Error('choose only one merge strategy')
  const body: Record<string, unknown> = { merge_method: methods[0] ?? 'merge' }
  const subject = fl.asStr('subject')
  const message = await bodyValue(inv, fl)
  const sha = fl.asStr('match_head_commit')
  if (subject !== undefined) body.commit_title = subject
  if (message !== undefined) body.commit_message = message
  if (sha !== undefined) body.sha = sha
  const [ref, number] = target(inv, fl)
  await mergePull(ghTransport(inv.config), ref, number, body)
  return textOut(`✓ Merged pull request ${ref.owner}/${ref.repo}#${String(number)}\n`)
}

export async function closeCmd(inv: CLIInvocation): Promise<CommandFnResult> {
  const fl = new FlagView(inv.flags)
  const [ref, number] = target(inv, fl)
  const edited = pull(await editPull(ghTransport(inv.config), ref, number, { state: 'closed' }))
  return textOut(
    `✓ Closed pull request ${ref.owner}/${ref.repo}#${String(number)} (${textValue(edited.title)})\n`,
  )
}

export async function commentCmd(inv: CLIInvocation): Promise<CommandFnResult> {
  const fl = new FlagView(inv.flags)
  const [ref, number] = target(inv, fl)
  const comment = pull(
    await commentPull(
      ghTransport(inv.config),
      ref,
      number,
      (await bodyValue(inv, fl, { required: true })) ?? '',
    ),
  )
  return textOut(`${textValue(comment.url)}\n`)
}

export async function diffCmd(inv: CLIInvocation): Promise<CommandFnResult> {
  const fl = new FlagView(inv.flags)
  const [ref, number] = target(inv, fl)
  const value = await diffPull(ghTransport(inv.config), ref, number)
  return textOut(value.endsWith('\n') ? value : `${value}\n`)
}

function check(value: Record<string, unknown>): Record<string, unknown> {
  const row = camel(value) as Record<string, unknown>
  row.link = row.detailsUrl ?? ''
  delete row.detailsUrl
  const output = row.output as { summary?: unknown } | undefined
  row.description = output?.summary ?? ''
  const state = textValue(row.conclusion ?? row.status)
  row.state = state
  row.bucket = BUCKETS[state] ?? 'pending'
  const app = row.app as { name?: unknown } | undefined
  row.workflow = app?.name ?? ''
  return row
}

export async function checksCmd(inv: CLIInvocation): Promise<CommandFnResult> {
  const fl = new FlagView(inv.flags)
  const [ref, number] = target(inv, fl)
  const rows = (await pullChecks(ghTransport(inv.config), ref, number)).map(check)
  const human = rows
    .map((row) => `${textValue(row.name)}\t${textValue(row.state)}\t${textValue(row.link)}\n`)
    .join('')
  const out = await typedOut(rows, fl, human, CHECK_FIELDS)
  if (out !== null) {
    const buckets = new Set(rows.map((row) => row.bucket))
    if (buckets.has('fail')) out[1].exitCode = 1
    else if (buckets.has('pending')) out[1].exitCode = 8
  }
  return out
}
