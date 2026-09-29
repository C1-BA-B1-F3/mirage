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

import type { GitHubTransport } from './client.ts'
import { githubPages } from './paginate.ts'
import type { RepoRef } from './repo.ts'

function path(ref: RepoRef, tail = ''): string {
  return `/repos/${ref.owner}/${ref.repo}/issues${tail}`
}

function onlyIssue(value: unknown, number: number): unknown {
  if (value !== null && typeof value === 'object' && 'pull_request' in value) {
    throw new Error(`#${String(number)} is a pull request, not an issue`)
  }
  return value
}

export async function listIssues(
  transport: GitHubTransport,
  ref: RepoRef,
  params: Record<string, string>,
  limit: number,
): Promise<Record<string, unknown>[]> {
  return githubPages(transport, path(ref), {
    params,
    limit,
    include: (row) => !('pull_request' in row),
  })
}

export async function getIssue(
  transport: GitHubTransport,
  ref: RepoRef,
  number: number,
): Promise<unknown> {
  return onlyIssue(await transport.get(path(ref, `/${String(number)}`)), number)
}

export function createIssue(
  transport: GitHubTransport,
  ref: RepoRef,
  body: Record<string, unknown>,
): Promise<unknown> {
  return transport.request('POST', path(ref), body)
}

export async function editIssue(
  transport: GitHubTransport,
  ref: RepoRef,
  number: number,
  body: Record<string, unknown>,
): Promise<unknown> {
  await getIssue(transport, ref, number)
  return transport.request('PATCH', path(ref, `/${String(number)}`), body)
}

export async function commentIssue(
  transport: GitHubTransport,
  ref: RepoRef,
  number: number,
  body: string,
): Promise<unknown> {
  await getIssue(transport, ref, number)
  return transport.request('POST', path(ref, `/${String(number)}/comments`), { body })
}

const COMMENTS_QUERY = `query($owner: String!, $repo: String!, $number: Int!, $cursor: String) {
  repository(owner: $owner, name: $repo) {
    issueOrPullRequest(number: $number) {
      ... on Issue {
        comments(first: 100, after: $cursor) {
          nodes { ...CommentFields }
          pageInfo { hasNextPage endCursor }
        }
      }
      ... on PullRequest {
        comments(first: 100, after: $cursor) {
          nodes { ...CommentFields }
          pageInfo { hasNextPage endCursor }
        }
      }
    }
  }
}
fragment CommentFields on IssueComment {
  id
  author { login }
  authorAssociation
  body
  createdAt
  includesCreatedEdit
  isMinimized
  minimizedReason
  reactionGroups { content users { totalCount } }
  url
  viewerDidAuthor
}`

export async function issueComments(
  transport: GitHubTransport,
  ref: RepoRef,
  number: number,
): Promise<Record<string, unknown>[]> {
  const rows: Record<string, unknown>[] = []
  let cursor: string | null = null
  for (;;) {
    const response = (await transport.request('POST', '/graphql', {
      query: COMMENTS_QUERY,
      variables: { owner: ref.owner, repo: ref.repo, number, cursor },
    })) as {
      errors?: { message: string }[]
      data?: {
        repository: {
          issueOrPullRequest: {
            comments: {
              nodes: Record<string, unknown>[]
              pageInfo: { hasNextPage: boolean; endCursor: string | null }
            }
          } | null
        } | null
      }
    }
    if (response.errors?.length) throw new Error(response.errors.map((e) => e.message).join('; '))
    const comments = response.data?.repository?.issueOrPullRequest?.comments
    if (!comments) throw new Error('Could not resolve comments for this issue or pull request')
    rows.push(...comments.nodes)
    if (!comments.pageInfo.hasNextPage) return rows
    const next = comments.pageInfo.endCursor
    if (!next || next === cursor) throw new Error('GitHub returned a non-advancing comments cursor')
    cursor = next
  }
}
