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
import {
  commentPull,
  commitStatuses,
  listPullRequestFields,
  listPulls,
  pullChecks,
  pullRequestFields,
} from './pull.ts'

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

describe('pullRequestFields', () => {
  it('asks for one pull request by number and returns its node', async () => {
    const sent: { query: string; variables: Record<string, unknown> }[] = []
    const reply = { data: { repository: { pullRequest: { title: 't' } } } }
    const node = await pullRequestFields(
      graphqlTransport([reply], sent),
      { owner: 'o', repo: 'r' },
      7,
      'title',
    )
    expect(node).toEqual({ title: 't' })
    expect(sent[0]?.variables).toEqual({ owner: 'o', repo: 'r', pr_number: 7 })
    expect(sent[0]?.query).toContain('pullRequest(number: $pr_number) {title}')
    expect(sent[0]?.query).not.toContain('$endCursor')
  })

  it('declares $endCursor only for a page after a cursor', async () => {
    const sent: { query: string; variables: Record<string, unknown> }[] = []
    const reply = { data: { repository: { pullRequest: {} } } }
    await pullRequestFields(
      graphqlTransport([reply], sent),
      { owner: 'o', repo: 'r' },
      7,
      'reviews(first: 100, after: $endCursor) {nodes {id}}',
      'c1',
    )
    expect(sent[0]?.query).toContain('$pr_number: Int!, $endCursor: String)')
    expect(sent[0]?.variables.endCursor).toBe('c1')
  })

  it('refuses a missing pull request the way gh words it', async () => {
    const reply = {
      data: { repository: { pullRequest: null } },
      errors: [
        {
          message: 'Could not resolve to a PullRequest with the number of 9.',
          path: ['repository', 'pullRequest'],
        },
      ],
    }
    await expect(
      pullRequestFields(graphqlTransport([reply], []), { owner: 'o', repo: 'r' }, 9, 'title'),
    ).rejects.toThrow(
      'GraphQL: Could not resolve to a PullRequest with the number of 9. (repository.pullRequest)',
    )
  })
})

describe('listPullRequestFields', () => {
  function page(numbers: number[], next: string | null) {
    return {
      data: {
        repository: {
          pullRequests: {
            nodes: numbers.map((number) => ({ number })),
            pageInfo: { hasNextPage: next !== null, endCursor: next },
          },
        },
      },
    }
  }

  it('pages until the limit, listing a repeated pull request once', async () => {
    const sent: { query: string; variables: Record<string, unknown> }[] = []
    const rows = await listPullRequestFields(
      graphqlTransport([page([9, 8], 'c1'), page([8, 7, 6], null)], sent),
      { owner: 'o', repo: 'r' },
      { states: ['OPEN'], base: 'main', head: undefined },
      3,
      'number',
    )
    expect(rows).toEqual([{ number: 9 }, { number: 8 }, { number: 7 }])
    expect(sent[0]?.variables).toEqual({
      owner: 'o',
      repo: 'r',
      limit: 3,
      state: ['OPEN'],
      baseBranch: 'main',
    })
    expect(sent[1]?.variables).toMatchObject({ endCursor: 'c1', limit: 1 })
    expect(sent[0]?.query).toContain('fragment pr on PullRequest{number}')
  })

  it('asks for nothing when the limit is zero', async () => {
    const sent: { query: string; variables: Record<string, unknown> }[] = []
    const rows = await listPullRequestFields(
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

describe('pullChecks', () => {
  function transportFor(
    checkRuns: unknown[],
    statuses: unknown[],
    seen: string[] = [],
  ): GitHubTransport {
    return {
      get: (path) => {
        seen.push(path)
        if (path.endsWith('/check-runs')) return Promise.resolve({ check_runs: checkRuns })
        if (path.endsWith('/status')) return Promise.resolve({ state: 'success', statuses })
        return Promise.resolve({ head: { sha: 'abc' } })
      },
      request: () => Promise.reject(new Error('unexpected request')),
    }
  }

  it('follows the head sha', async () => {
    const seen: string[] = []

    const rows = await pullChecks(
      transportFor([{ name: 'test' }], [], seen),
      {
        owner: 'o',
        repo: 'r',
      },
      3,
    )

    expect(rows).toEqual([{ name: 'test' }])
    expect(seen).toContain('/repos/o/r/commits/abc/check-runs')
  })

  it('merges commit status contexts', async () => {
    const rows = await pullChecks(
      transportFor(
        [],
        [
          {
            context: 'ci/legacy',
            state: 'failure',
            target_url: 'https://ci.test/1',
            description: 'boom',
            created_at: '2026-01-01T00:00:00Z',
            updated_at: '2026-01-01T00:01:00Z',
          },
          { context: 'ci/slow', state: 'pending' },
        ],
      ),
      { owner: 'o', repo: 'r' },
      3,
    )

    expect(rows).toEqual([
      {
        name: 'ci/legacy',
        status: 'completed',
        conclusion: 'failure',
        details_url: 'https://ci.test/1',
        output: { summary: 'boom' },
        started_at: '2026-01-01T00:00:00Z',
        completed_at: '2026-01-01T00:01:00Z',
      },
      {
        name: 'ci/slow',
        status: 'pending',
        conclusion: null,
        details_url: '',
        output: { summary: '' },
        started_at: null,
        completed_at: null,
      },
    ])
  })
})

describe('commitStatuses', () => {
  it('reads the combined endpoint and drops non-objects', async () => {
    const seen: string[] = []
    const transport: GitHubTransport = {
      get: (path) => {
        seen.push(path)
        return Promise.resolve({ state: 'success', statuses: [{ context: 'ci' }, 'junk'] })
      },
      request: () => Promise.reject(new Error('unexpected request')),
    }

    expect(await commitStatuses(transport, { owner: 'o', repo: 'r' }, 'abc')).toEqual([
      { context: 'ci' },
    ])
    expect(seen).toEqual(['/repos/o/r/commits/abc/status'])
  })
})

describe('commentPull', () => {
  it('preflights the pull request number', async () => {
    const calls: { method: string; path: string }[] = []
    const transport: GitHubTransport = {
      get: (path) => {
        calls.push({ method: 'GET', path })
        return Promise.reject(new Error('not a pull request'))
      },
      request: (method, path) => {
        calls.push({ method, path })
        return Promise.resolve({})
      },
    }

    await expect(commentPull(transport, { owner: 'o', repo: 'r' }, 4, 'no')).rejects.toThrow(
      'not a pull request',
    )
    expect(calls).toEqual([{ method: 'GET', path: '/repos/o/r/pulls/4' }])
  })
})

describe('listPulls', () => {
  it('filters before applying the limit', async () => {
    const seen: string[] = []
    const transport: GitHubTransport = {
      get: (_path, params = {}) => {
        seen.push(params.page ?? '')
        return Promise.resolve(
          params.page === '1'
            ? [{ number: 2, merged_at: null }]
            : [{ number: 1, merged_at: 'now' }],
        )
      },
      request: () => Promise.reject(new Error('unexpected request')),
    }

    const rows = await listPulls(
      transport,
      { owner: 'o', repo: 'r' },
      { state: 'closed' },
      1,
      (row) => row.merged_at !== null,
    )

    expect(rows).toEqual([{ number: 1, merged_at: 'now' }])
    expect(seen).toEqual(['1', '2'])
  })
})
