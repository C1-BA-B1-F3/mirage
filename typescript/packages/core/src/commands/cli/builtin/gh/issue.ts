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

import { FlagView } from '../../../spec/flag_view.ts'
import type { CommandFnResult } from '../../../config.ts'
import type { CLIInvocation } from '../../types.ts'
import {
  commentIssue,
  createIssue,
  editIssue,
  getIssue,
  listIssues,
  issueComments,
} from '../../../../core/github/issue.ts'
import {
  bodyValue,
  camel,
  csvValues,
  ghTransport,
  repoFor,
  repoNumber,
  textOut,
  textValue,
  typedOut,
} from './accessor.ts'

export const ISSUE_FIELDS = [
  'assignees',
  'author',
  'body',
  'closed',
  'createdAt',
  'labels',
  'number',
  'state',
  'title',
  'updatedAt',
  'url',
] as const

function issue(value: unknown): Record<string, unknown> {
  const row = camel(value)
  const result = row !== null && typeof row === 'object' ? (row as Record<string, unknown>) : {}
  result.closed = textValue(result.state).toLowerCase() === 'closed'
  return result
}

function names(value: unknown, key: 'login' | 'name'): string[] {
  if (!Array.isArray(value)) return []
  return value
    .filter((item): item is Record<string, unknown> => item !== null && typeof item === 'object')
    .map((item) => textValue(item[key] ?? item.name))
    .filter(Boolean)
}

function labels(row: Record<string, unknown>): string {
  return names(row.labels, 'name').join(', ')
}

function listText(rows: Record<string, unknown>[]): string {
  return rows
    .map(
      (row) =>
        `${textValue(row.number)}\t${textValue(row.state).toUpperCase()}\t${textValue(row.title)}\t${labels(row)}\n`,
    )
    .join('')
}

function viewText(row: Record<string, unknown>): string {
  const author = row.author as { login?: unknown } | undefined
  return `title:\t${textValue(row.title)}\nstate:\t${textValue(row.state).toUpperCase()}\nauthor:\t${textValue(author?.login)}\nlabels:\t${labels(row)}\n--\n${textValue(row.body)}\n`
}

function target(inv: CLIInvocation, fl: FlagView) {
  return repoNumber(inv, fl, inv.texts[0], 'issue', 'issues')
}

export async function listCmd(inv: CLIInvocation): Promise<CommandFnResult> {
  const fl = new FlagView(inv.flags)
  const params: Record<string, string> = { state: fl.asStr('state') ?? 'open' }
  const assignee = fl.asStr('assignee')
  const author = fl.asStr('author')
  const labelValues = csvValues(fl.asList('label'))
  if (assignee !== undefined) params.assignee = assignee
  if (author !== undefined) params.creator = author
  if (labelValues.length > 0) params.labels = labelValues.join(',')
  const values = await listIssues(
    ghTransport(inv.config),
    repoFor(inv, fl),
    params,
    fl.asInt('limit') ?? 30,
  )
  const rows = values.map(issue)
  return typedOut(rows, fl, listText(rows), ISSUE_FIELDS)
}

export async function viewCmd(inv: CLIInvocation): Promise<CommandFnResult> {
  const fl = new FlagView(inv.flags)
  const [ref, number] = target(inv, fl)
  const row = issue(await getIssue(ghTransport(inv.config), ref, number))
  const comments = await commentsFor(inv, fl, ref, number)
  if (comments !== null) row.comments = comments
  return typedOut(row, fl, fl.asBool('comments') ? commentsText(comments ?? []) : viewText(row), [
    ...ISSUE_FIELDS,
    'comments',
  ])
}

export async function createCmd(inv: CLIInvocation): Promise<CommandFnResult> {
  const fl = new FlagView(inv.flags)
  const title = fl.asStr('title')
  if (title === undefined || title === '')
    throw new Error('--title is required in noninteractive mode')
  const body: Record<string, unknown> = { title, body: (await bodyValue(inv, fl)) ?? '' }
  const labelValues = csvValues(fl.asList('label'))
  const assignees = csvValues(fl.asList('assignee'))
  if (labelValues.length > 0) body.labels = labelValues
  if (assignees.length > 0) body.assignees = assignees
  const created = issue(await createIssue(ghTransport(inv.config), repoFor(inv, fl), body))
  return textOut(`${textValue(created.url)}\n`)
}

export async function editCmd(inv: CLIInvocation): Promise<CommandFnResult> {
  const fl = new FlagView(inv.flags)
  const transport = ghTransport(inv.config)
  const [ref, number] = target(inv, fl)
  const body: Record<string, unknown> = {}
  const title = fl.asStr('title')
  const text = await bodyValue(inv, fl)
  if (title !== undefined) body.title = title
  if (text !== undefined) body.body = text
  const additions = csvValues(fl.asList('add_label'))
  const removals = new Set(csvValues(fl.asList('remove_label')))
  const addAssignees = csvValues(fl.asList('add_assignee'))
  const removeAssignees = new Set(csvValues(fl.asList('remove_assignee')))
  if (
    additions.length > 0 ||
    removals.size > 0 ||
    addAssignees.length > 0 ||
    removeAssignees.size > 0
  ) {
    const current = issue(await getIssue(transport, ref, number))
    if (additions.length > 0 || removals.size > 0) {
      body.labels = [
        ...new Set([
          ...names(current.labels, 'name').filter((name) => !removals.has(name)),
          ...additions,
        ]),
      ]
    }
    if (addAssignees.length > 0 || removeAssignees.size > 0) {
      body.assignees = [
        ...new Set([
          ...names(current.assignees, 'login').filter((name) => !removeAssignees.has(name)),
          ...addAssignees,
        ]),
      ]
    }
  }
  if (Object.keys(body).length === 0) throw new Error('no issue fields to edit')
  const edited = issue(await editIssue(transport, ref, number, body))
  return textOut(`${textValue(edited.url)}\n`)
}

async function state(inv: CLIInvocation, next: 'open' | 'closed'): Promise<CommandFnResult> {
  const fl = new FlagView(inv.flags)
  const [ref, number] = target(inv, fl)
  const edited = issue(await editIssue(ghTransport(inv.config), ref, number, { state: next }))
  const verb = next === 'closed' ? 'Closed' : 'Reopened'
  return textOut(
    `✓ ${verb} issue ${ref.owner}/${ref.repo}#${String(number)} (${textValue(edited.title)})\n`,
  )
}

export async function closeCmd(inv: CLIInvocation): Promise<CommandFnResult> {
  return state(inv, 'closed')
}

export async function reopenCmd(inv: CLIInvocation): Promise<CommandFnResult> {
  return state(inv, 'open')
}

export async function commentCmd(inv: CLIInvocation): Promise<CommandFnResult> {
  const fl = new FlagView(inv.flags)
  const body = await bodyValue(inv, fl, { required: true })
  const [ref, number] = target(inv, fl)
  const comment = issue(await commentIssue(ghTransport(inv.config), ref, number, body ?? ''))
  return textOut(`${textValue(comment.url)}\n`)
}

export async function commentsFor(
  inv: CLIInvocation,
  fl: FlagView,
  ref: { owner: string; repo: string },
  number: number,
): Promise<Record<string, unknown>[] | null> {
  if (!fl.asBool('comments') && !(fl.asStr('json') ?? '').split(',').includes('comments'))
    return null
  const rows = await issueComments(ghTransport(inv.config), ref, number)
  return rows.map((row) => ({
    ...row,
    author: row.author ?? { login: '' },
    minimizedReason: row.minimizedReason ?? '',
    reactionGroups: (row.reactionGroups as { users: { totalCount: number } }[]).filter(
      (group) => group.users.totalCount > 0,
    ),
  }))
}

export function commentsText(rows: Record<string, unknown>[]): string {
  return rows
    .map(
      (row) =>
        `author:\t${textValue((row.author as { login: string } | null)?.login)}\nassociation:\t${textValue(row.authorAssociation).toLowerCase()}\nedited:\t${String(row.includesCreatedEdit)}\nstatus:\t${row.isMinimized ? textValue(row.minimizedReason).toLowerCase() : 'none'}\n--\n${textValue(row.body)}\n--\n`,
    )
    .join('')
}
