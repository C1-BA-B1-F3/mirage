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

import { GitHubApiError, type GitHubTransport } from './client.ts'
import { decodeBase64 } from '../../utils/base64.ts'
import { githubPages } from './paginate.ts'

export interface RepoRef {
  owner: string
  repo: string
}

/**
 * gh's `[HOST/]OWNER/REPO`: the host is optional and leading, so the owner and
 * the repository are always the last two segments. Taking the first two
 * instead read `github.com/acme/tools` as owner `github.com`, repo `acme` --
 * a different repository, reported as success.
 *
 * Args:
 *   spec (string): the repository as the line spelled it.
 *
 * Returns:
 *   RepoRef: the owner and repository names.
 */
export function parseRepo(spec: string): RepoRef {
  const parts = spec.split('/')
  const repo = parts.pop()
  const owner = parts.pop()
  if (owner === undefined || repo === undefined || owner === '' || repo === '') {
    throw new Error(`expected the "[HOST/]OWNER/REPO" format, got "${spec}"`)
  }
  // One more segment is a host; two is not a repository any spelling reaches.
  if (parts.length > 1) {
    throw new Error(`expected the "[HOST/]OWNER/REPO" format, got "${spec}"`)
  }
  return { owner, repo }
}

export async function login(transport: GitHubTransport): Promise<string> {
  const me = (await transport.get('/user')) as { login?: string }
  return me.login ?? ''
}

export function viewRepo(transport: GitHubTransport, ref: RepoRef): Promise<unknown> {
  return transport.get(`/repos/${ref.owner}/${ref.repo}`)
}

interface GraphQLErrorRow {
  message?: string
  path?: (string | number)[]
}

/**
 * Run one GraphQL query and return its data, refusing the way gh does.
 *
 * gh names each error with the path of the field that raised it and joins
 * them: `GraphQL: Could not resolve to a Repository with the name 'o/r'.
 * (repository)`.
 */
async function graphqlData(
  transport: GitHubTransport,
  query: string,
  variables: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const response = (await transport.request('POST', '/graphql', { query, variables })) as {
    data?: Record<string, unknown> | null
    errors?: GraphQLErrorRow[]
  }
  if (response.errors !== undefined && response.errors.length > 0) {
    const messages = response.errors.map((error) => {
      const path = (error.path ?? []).map(String).join('.')
      return path === '' ? (error.message ?? '') : `${error.message ?? ''} (${path})`
    })
    throw new Error(`GraphQL: ${messages.join(', ')}`)
  }
  return response.data ?? {}
}

/**
 * The selected fields of one repository, over GraphQL, as gh reads them for
 * `repo view --json`: one query naming only what was asked for.
 *
 * Args:
 *   transport (GitHubTransport): the API client.
 *   ref (RepoRef): the repository.
 *   selection (string): the GraphQL selection inside `repository { }`.
 */
export async function repositoryFields(
  transport: GitHubTransport,
  ref: RepoRef,
  selection: string,
): Promise<Record<string, unknown>> {
  const data = await graphqlData(
    transport,
    `query RepositoryInfo($owner: String!, $name: String!) {\n` +
      `    repository(owner: $owner, name: $name) {${selection}}\n  }`,
    { owner: ref.owner, name: ref.repo },
  )
  return (data.repository ?? {}) as Record<string, unknown>
}

/**
 * The selected fields of an owner's repositories, over GraphQL, as gh reads
 * them for `repo list --json`: the owner's own, most recently pushed first, a
 * page of up to 100 at a time until `limit`. No owner means the viewer.
 *
 * Args:
 *   transport (GitHubTransport): the API client.
 *   owner (string | undefined): the user or organization, or the viewer.
 *   limit (number): how many repositories at most.
 *   selection (string): the GraphQL selection for each repository.
 */
export async function listRepositoryFields(
  transport: GitHubTransport,
  owner: string | undefined,
  limit: number,
  selection: string,
): Promise<Record<string, unknown>[]> {
  const head =
    owner === undefined
      ? 'query RepositoryList($perPage:Int!,$endCursor:String,$privacy:RepositoryPrivacy,' +
        '$fork:Boolean) {\n    repositoryOwner: viewer {'
      : 'query RepositoryList($perPage:Int!,$endCursor:String,$privacy:RepositoryPrivacy,' +
        '$fork:Boolean,$owner:String!) {\n    repositoryOwner(login: $owner) {'
  const query =
    `${head}\n      login\n      repositories(first: $perPage, after: $endCursor, ` +
    'privacy: $privacy, isFork: $fork, ownerAffiliations: OWNER, orderBy: { field: ' +
    `PUSHED_AT, direction: DESC }) {\n        nodes{${selection}}\n        totalCount\n` +
    '        pageInfo{hasNextPage,endCursor}\n      }\n    }\n  }'
  const rows: Record<string, unknown>[] = []
  let cursor: string | null = null
  while (rows.length < limit) {
    const variables: Record<string, unknown> = { perPage: Math.min(limit, 100) }
    if (owner !== undefined) variables.owner = owner
    if (cursor !== null) variables.endCursor = cursor
    const data = await graphqlData(transport, query, variables)
    const page = (
      data.repositoryOwner as {
        repositories?: {
          nodes?: Record<string, unknown>[]
          pageInfo?: { hasNextPage?: boolean; endCursor?: string | null }
        }
      } | null
    )?.repositories
    rows.push(...(page?.nodes ?? []))
    const next = page?.pageInfo?.endCursor ?? null
    if (page?.pageInfo?.hasNextPage !== true || next === null || next === cursor) break
    cursor = next
  }
  return rows.slice(0, limit)
}

/**
 * The repository's README as text, or null when it has none.
 */
export async function readReadme(transport: GitHubTransport, ref: RepoRef): Promise<string | null> {
  let data: unknown
  try {
    data = await transport.get(`/repos/${ref.owner}/${ref.repo}/readme`)
  } catch (err) {
    if (err instanceof GitHubApiError && err.status === 404) return null
    throw err
  }
  const content = (data as { content?: unknown } | null)?.content
  if (typeof content !== 'string') return null
  return new TextDecoder().decode(decodeBase64(content))
}

export function forkRepo(
  transport: GitHubTransport,
  ref: RepoRef,
  name?: string,
): Promise<unknown> {
  const body = name === undefined ? {} : { name }
  return transport.request('POST', `/repos/${ref.owner}/${ref.repo}/forks`, body)
}

export function renameRepo(
  transport: GitHubTransport,
  ref: RepoRef,
  name: string,
): Promise<unknown> {
  return transport.request('PATCH', `/repos/${ref.owner}/${ref.repo}`, { name })
}

export async function listRepos(
  transport: GitHubTransport,
  owner: string | undefined,
  limit: number,
): Promise<Record<string, unknown>[]> {
  let path = '/user/repos'
  if (owner !== undefined) {
    const account = (await transport.get(`/users/${owner}`)) as { type?: unknown }
    const prefix = account.type === 'Organization' ? 'orgs' : 'users'
    path = `/${prefix}/${owner}/repos`
  }
  return githubPages(transport, path, { params: { sort: 'pushed' }, limit })
}

export async function createRepo(
  transport: GitHubTransport,
  owner: string | undefined,
  body: Record<string, unknown>,
): Promise<unknown> {
  const personal =
    owner === undefined || owner.toLowerCase() === (await login(transport)).toLowerCase()
  const path = personal ? '/user/repos' : `/orgs/${owner}/repos`
  return transport.request('POST', path, body)
}
