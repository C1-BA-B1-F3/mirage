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

import { describe, expect, it } from 'vitest'
import type { GitHubTransport } from './client.ts'
import { GRAPHQL_PATH } from './constants.ts'
import { commentIssue, editIssue, getIssue, issueFields, listIssueFields } from './issue.ts'

/** A transport that answers each GraphQL request with the next reply. */
function graphqlTransport(
  replies: unknown[],
  sent: { query: string; variables: Record<string, unknown> }[],
): GitHubTransport {
  return {
    get: () => Promise.reject(new Error('unexpected GET')),
    request: (_method, path, body) => {
      if (path !== GRAPHQL_PATH) return Promise.reject(new Error(`unexpected ${path}`))
      sent.push(body as { query: string; variables: Record<string, unknown> })
      return Promise.resolve(replies.shift())
    },
  }
}

describe('direct issue verbs', () => {
  it.each(['get', 'edit', 'comment'] as const)(
    'rejects a pull request number for %s',
    async (verb) => {
      const calls: { method: string; path: string }[] = []
      const transport: GitHubTransport = {
        get: (path) => {
          calls.push({ method: 'GET', path })
          return Promise.resolve({ number: 4, pull_request: { url: 'x' } })
        },
        request: (method, path) => {
          calls.push({ method, path })
          return Promise.resolve({})
        },
      }
      const ref = { owner: 'o', repo: 'r' }
      const operation =
        verb === 'get'
          ? getIssue(transport, ref, 4)
          : verb === 'edit'
            ? editIssue(transport, ref, 4, { state: 'closed' })
            : commentIssue(transport, ref, 4, 'no')

      await expect(operation).rejects.toThrow('pull request, not an issue')
      expect(calls).toEqual([{ method: 'GET', path: '/repos/o/r/issues/4' }])
    },
  )
})

describe('issueFields', () => {
  it('asks for the number as an issue or a pull request, each half its own selection', async () => {
    const sent: { query: string; variables: Record<string, unknown> }[] = []
    const reply = {
      data: { repository: { hasIssuesEnabled: true, issue: { __typename: 'Issue', title: 't' } } },
    }
    const node = await issueFields(graphqlTransport([reply], sent), { owner: 'o', repo: 'r' }, 4, {
      issue: 'title,isPinned',
      pull: 'title',
    })
    expect(node).toEqual({ __typename: 'Issue', title: 't' })
    expect(sent[0]?.variables).toEqual({ owner: 'o', repo: 'r', number: 4 })
    expect(sent[0]?.query).toContain('issue: issueOrPullRequest(number: $number)')
    expect(sent[0]?.query).toContain('...on Issue{title,isPinned}')
    expect(sent[0]?.query).toContain('...on PullRequest{title}')
    expect(sent[0]?.query).not.toContain('$endCursor')
  })

  it('leaves an empty half out and declares $endCursor for a later page', async () => {
    const sent: { query: string; variables: Record<string, unknown> }[] = []
    const reply = { data: { repository: { issue: { __typename: 'PullRequest' } } } }
    await issueFields(
      graphqlTransport([reply], sent),
      { owner: 'o', repo: 'r' },
      4,
      { issue: '', pull: 'comments(first: 100, after: $endCursor) {nodes {id}}' },
      'c1',
    )
    expect(sent[0]?.query).toContain('$number: Int!, $endCursor: String)')
    expect(sent[0]?.query).not.toContain('...on Issue')
    expect(sent[0]?.variables.endCursor).toBe('c1')
  })

  it.each([
    [false, "the 'o/r' repository has disabled issues"],
    [true, 'issue was not found but GraphQL reported no error'],
  ])('refuses an answer with no issue (issues enabled: %s)', async (enabled, message) => {
    const reply = { data: { repository: { hasIssuesEnabled: enabled, issue: null } } }
    await expect(
      issueFields(graphqlTransport([reply], []), { owner: 'o', repo: 'r' }, 4, {
        issue: 'title',
        pull: 'title',
      }),
    ).rejects.toThrow(message)
  })
})

describe('listIssueFields', () => {
  function page(numbers: number[], next: string | null) {
    return {
      data: {
        repository: {
          hasIssuesEnabled: true,
          issues: {
            nodes: numbers.map((number) => ({ number })),
            pageInfo: { hasNextPage: next !== null, endCursor: next },
          },
        },
      },
    }
  }

  it('pages newest first until the limit, with the narrowing gh sends', async () => {
    const sent: { query: string; variables: Record<string, unknown> }[] = []
    const rows = await listIssueFields(
      graphqlTransport([page([9, 8], 'c1'), page([7, 6], null)], sent),
      { owner: 'o', repo: 'r' },
      { states: ['OPEN', 'CLOSED'], author: 'me', labels: ['bug'] },
      3,
      'number',
    )
    expect(rows).toEqual([{ number: 9 }, { number: 8 }, { number: 7 }])
    expect(sent[0]?.variables).toEqual({
      owner: 'o',
      repo: 'r',
      states: ['OPEN', 'CLOSED'],
      limit: 3,
      author: 'me',
      labels: ['bug'],
    })
    expect(sent[1]?.variables).toMatchObject({ endCursor: 'c1', limit: 1 })
    expect(sent[0]?.query).toContain('fragment issue on Issue {number}')
    expect(sent[0]?.query).toContain('orderBy: {field: CREATED_AT, direction: DESC}')
  })

  it('refuses a repository with issues disabled', async () => {
    const reply = { data: { repository: { hasIssuesEnabled: false, issues: null } } }
    await expect(
      listIssueFields(
        graphqlTransport([reply], []),
        { owner: 'o', repo: 'r' },
        { states: ['OPEN'] },
        30,
        'number',
      ),
    ).rejects.toThrow("the 'o/r' repository has disabled issues")
  })

  it('asks for nothing when the limit is zero', async () => {
    const sent: { query: string; variables: Record<string, unknown> }[] = []
    const rows = await listIssueFields(
      graphqlTransport([], sent),
      { owner: 'o', repo: 'r' },
      { states: ['OPEN'] },
      0,
      'number',
    )
    expect(rows).toEqual([])
    expect(sent).toEqual([])
  })
})
