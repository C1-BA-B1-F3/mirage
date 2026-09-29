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
import {
  createRepo,
  forkRepo,
  listRepos,
  listRepositoryFields,
  login,
  readReadme,
  renameRepo,
  repositoryFields,
  viewRepo,
} from '../../../../core/github/repo.ts'
import type { CommandFnResult } from '../../../config.ts'
import type { CLIInvocation } from '../../types.ts'
import { camel, ghRepo, ghTransport, jsonFields, textOut, textValue, typedOut } from './accessor.ts'

/**
 * The Go type gh decodes a field into, which is what decides how it prints.
 *
 * A string prints `""` for null, a number 0 and a bool false; `time` is a
 * non-pointer `time.Time`, whose zero is the year-one timestamp; `raw` is a
 * pointer (or a nullable time) and stays null. A struct prints every one of
 * its fields in its own order, zero-filled where the query asked for fewer
 * (a user's `databaseId` is always there, as 0), and prints null only when it
 * is a pointer. A list prints null when the answer carried none. Each struct
 * field may read a differently spelled key from the answer: an untagged Go
 * field prints under its own name.
 */
type Shape =
  | 'string'
  | 'int'
  | 'bool'
  | 'time'
  | 'raw'
  | {
      readonly fields: readonly (readonly [string, Shape, string?])[]
      readonly nullable: boolean
    }
  | { readonly list: Shape }

const ZERO_TIME = '0001-01-01T00:00:00Z'

function struct(...fields: (readonly [string, Shape, string?])[]): Shape {
  return { fields, nullable: false }
}

function pointer(...fields: (readonly [string, Shape, string?])[]): Shape {
  return { fields, nullable: true }
}

function list(shape: Shape): Shape {
  return { list: shape }
}

/** One value as gh prints it once decoded into `shape`. */
function exported(value: unknown, shape: Shape): unknown {
  if (shape === 'string') return typeof value === 'string' ? value : ''
  if (shape === 'int') return typeof value === 'number' ? value : 0
  if (shape === 'bool') return typeof value === 'boolean' ? value : false
  if (shape === 'time') return typeof value === 'string' ? value : ZERO_TIME
  if (shape === 'raw') return value ?? null
  if ('list' in shape) {
    return Array.isArray(value) ? value.map((item) => exported(item, shape.list)) : null
  }
  if ((value === null || value === undefined) && shape.nullable) return null
  const row = value !== null && typeof value === 'object' ? (value as Record<string, unknown>) : {}
  return Object.fromEntries(
    shape.fields.map(([name, inner, source]) => [name, exported(row[source ?? name], inner)]),
  )
}

const OWNER = struct(['id', 'string'], ['login', 'string'])
const USER = struct(
  ['id', 'string'],
  ['login', 'string'],
  ['name', 'string'],
  ['databaseId', 'int'],
)
const COUNT = struct(['totalCount', 'int'])
// gh prints a related repository (a fork's parent, a template) as three facts.
const RELATED = pointer(['id', 'string'], ['name', 'string'], ['owner', OWNER])

/**
 * One `--json` field: the GraphQL selection gh sends for it and how the answer
 * prints. `unwrap` names gh's own flattening of a connection: its `nodes`,
 * its `edges`, or the topic inside each topic node, which prints null rather
 * than `[]` for a repository with none.
 */
interface RepoField {
  readonly select: string
  readonly shape: Shape
  readonly unwrap?: 'nodes' | 'edges' | 'topics'
}

function plain(name: string, shape: Shape): readonly [string, RepoField] {
  return [name, { select: name, shape }]
}

/**
 * Every field `gh repo view --json` and `gh repo list --json` accept in gh
 * 2.85, each with the selection gh put on the wire for it (captured with
 * `GH_DEBUG=api`) and the shape of gh's own `Repository` type.
 */
const REPO_FIELD_TABLE: ReadonlyMap<string, RepoField> = new Map<string, RepoField>([
  plain('archivedAt', 'raw'),
  [
    'assignableUsers',
    {
      select: 'assignableUsers(first:100){nodes{id,login,name}}',
      shape: list(USER),
      unwrap: 'nodes',
    },
  ],
  [
    'codeOfConduct',
    {
      select: 'codeOfConduct{key,name,url}',
      shape: pointer(['key', 'string'], ['name', 'string'], ['url', 'string']),
    },
  ],
  [
    'contactLinks',
    {
      select: 'contactLinks{about,name,url}',
      shape: list(struct(['about', 'string'], ['name', 'string'], ['url', 'string'])),
    },
  ],
  plain('createdAt', 'time'),
  ['defaultBranchRef', { select: 'defaultBranchRef{name}', shape: struct(['name', 'string']) }],
  plain('deleteBranchOnMerge', 'bool'),
  plain('description', 'string'),
  plain('diskUsage', 'int'),
  plain('forkCount', 'int'),
  [
    'fundingLinks',
    {
      select: 'fundingLinks{platform,url}',
      shape: list(struct(['platform', 'string'], ['url', 'string'])),
    },
  ],
  plain('hasDiscussionsEnabled', 'bool'),
  plain('hasIssuesEnabled', 'bool'),
  plain('hasProjectsEnabled', 'bool'),
  plain('hasWikiEnabled', 'bool'),
  plain('homepageUrl', 'string'),
  plain('id', 'string'),
  plain('isArchived', 'bool'),
  plain('isBlankIssuesEnabled', 'bool'),
  plain('isEmpty', 'bool'),
  plain('isFork', 'bool'),
  plain('isInOrganization', 'bool'),
  plain('isMirror', 'bool'),
  plain('isPrivate', 'bool'),
  plain('isSecurityPolicyEnabled', 'bool'),
  plain('isTemplate', 'bool'),
  plain('isUserConfigurationRepository', 'bool'),
  [
    'issueTemplates',
    {
      select: 'issueTemplates{name,title,body,about}',
      shape: list(
        struct(['name', 'string'], ['title', 'string'], ['body', 'string'], ['about', 'string']),
      ),
    },
  ],
  ['issues', { select: 'issues(states:OPEN){totalCount}', shape: COUNT }],
  [
    'labels',
    {
      select: 'labels(first:100){nodes{id,color,name,description}}',
      shape: list(
        struct(
          ['id', 'string'],
          ['name', 'string'],
          ['description', 'string'],
          ['color', 'string'],
        ),
      ),
      unwrap: 'nodes',
    },
  ],
  [
    'languages',
    {
      select: 'languages(first:100){edges{size,node{name}}}',
      shape: list(struct(['size', 'int'], ['node', struct(['name', 'string'])])),
      unwrap: 'edges',
    },
  ],
  [
    'latestRelease',
    {
      select: 'latestRelease{publishedAt,tagName,name,url}',
      shape: pointer(
        ['name', 'string'],
        ['tagName', 'string'],
        ['url', 'string'],
        ['publishedAt', 'time'],
      ),
    },
  ],
  [
    'licenseInfo',
    {
      select: 'licenseInfo{key,name,nickname}',
      shape: pointer(['key', 'string'], ['name', 'string'], ['nickname', 'string']),
    },
  ],
  [
    'mentionableUsers',
    {
      select: 'mentionableUsers(first:100){nodes{id,login,name}}',
      shape: list(USER),
      unwrap: 'nodes',
    },
  ],
  plain('mergeCommitAllowed', 'bool'),
  [
    'milestones',
    {
      select: 'milestones(first:100,states:OPEN){nodes{number,title,description,dueOn}}',
      shape: list(
        struct(['number', 'int'], ['title', 'string'], ['description', 'string'], ['dueOn', 'raw']),
      ),
      unwrap: 'nodes',
    },
  ],
  plain('mirrorUrl', 'string'),
  plain('name', 'string'),
  plain('nameWithOwner', 'string'),
  plain('openGraphImageUrl', 'string'),
  ['owner', { select: 'owner{id,login}', shape: OWNER }],
  ['parent', { select: 'parent{id,name,owner{id,login}}', shape: RELATED }],
  ['primaryLanguage', { select: 'primaryLanguage{name}', shape: pointer(['name', 'string']) }],
  [
    'projects',
    {
      select: 'projects(first:100,states:OPEN){nodes{id,name,number,body,resourcePath}}',
      shape: list(
        struct(['id', 'string'], ['name', 'string'], ['number', 'int'], ['resourcePath', 'string']),
      ),
      unwrap: 'nodes',
    },
  ],
  // gh has no flattening for this one, so it prints its Go struct as is:
  // the untagged `Nodes` field under its own capitalised name.
  [
    'projectsV2',
    {
      select:
        'projectsV2(first:100,query:"is:open"){nodes{id,number,title,resourcePath,closed,url}}',
      shape: struct([
        'Nodes',
        list(
          struct(
            ['id', 'string'],
            ['title', 'string'],
            ['number', 'int'],
            ['resourcePath', 'string'],
            ['closed', 'bool'],
            ['url', 'string'],
          ),
        ),
        'nodes',
      ]),
    },
  ],
  [
    'pullRequestTemplates',
    {
      select: 'pullRequestTemplates{body,filename}',
      shape: list(struct(['filename', 'string'], ['body', 'string'])),
    },
  ],
  ['pullRequests', { select: 'pullRequests(states:OPEN){totalCount}', shape: COUNT }],
  plain('pushedAt', 'raw'),
  plain('rebaseMergeAllowed', 'bool'),
  [
    'repositoryTopics',
    {
      select: 'repositoryTopics(first:100){nodes{topic{name}}}',
      shape: list(struct(['name', 'string'])),
      unwrap: 'topics',
    },
  ],
  plain('securityPolicyUrl', 'string'),
  plain('squashMergeAllowed', 'bool'),
  plain('sshUrl', 'string'),
  plain('stargazerCount', 'int'),
  ['templateRepository', { select: 'templateRepository{id,name,owner{id,login}}', shape: RELATED }],
  plain('updatedAt', 'time'),
  plain('url', 'string'),
  plain('usesCustomOpenGraphImage', 'bool'),
  plain('viewerCanAdminister', 'bool'),
  plain('viewerDefaultCommitEmail', 'string'),
  plain('viewerDefaultMergeMethod', 'string'),
  plain('viewerHasStarred', 'bool'),
  plain('viewerPermission', 'string'),
  plain('viewerPossibleCommitEmails', list('string')),
  plain('viewerSubscription', 'string'),
  plain('visibility', 'string'),
  ['watchers', { select: 'watchers{totalCount}', shape: COUNT }],
])

export const REPO_FIELDS: readonly string[] = [...REPO_FIELD_TABLE.keys()]

/** The GraphQL selection for the fields a line asked for, in its order. */
function repoSelection(fields: readonly string[]): string {
  return [...new Set(fields)].map((field) => REPO_FIELD_TABLE.get(field)?.select ?? field).join(',')
}

/** One repository's answer as gh exports the fields asked for. */
function exportedRepo(
  node: Record<string, unknown>,
  fields: readonly string[],
): Record<string, unknown> {
  const row: Record<string, unknown> = {}
  for (const field of fields) {
    const spec = REPO_FIELD_TABLE.get(field)
    if (spec === undefined) continue
    let value = node[field]
    const connection =
      value !== null && typeof value === 'object' ? (value as Record<string, unknown>) : null
    if (spec.unwrap === 'nodes') value = connection?.nodes
    if (spec.unwrap === 'edges') value = connection?.edges
    if (spec.unwrap === 'topics') {
      const topics = Array.isArray(connection?.nodes)
        ? (connection.nodes as { topic?: unknown }[]).map((item) => item.topic)
        : []
      value = topics.length > 0 ? topics : null
    }
    row[field] = exported(value, spec.shape)
  }
  return row
}

function repo(value: unknown): Record<string, unknown> {
  const row = camel(value)
  const result = row !== null && typeof row === 'object' ? (row as Record<string, unknown>) : {}
  if ('fullName' in result) {
    result.nameWithOwner = result.fullName
    delete result.fullName
  }
  if ('defaultBranch' in result) {
    result.defaultBranchRef = { name: result.defaultBranch }
    delete result.defaultBranch
  }
  if ('private' in result) {
    result.isPrivate = result.private
    delete result.private
  }
  if ('fork' in result) {
    result.isFork = result.fork
    delete result.fork
  }
  return result
}

/**
 * gh's own text view of a repository: two tab-separated header lines and
 * then the README verbatim, with the `--` separator omitted entirely when
 * there is no README. Probed against gh 2.85, whose description line is
 * present and empty for a repository that has none.
 */
export function summary(repo: unknown, readme: string | null): string {
  const fields = (repo ?? {}) as { full_name?: unknown; description?: unknown }
  const name = typeof fields.full_name === 'string' ? fields.full_name : ''
  const description = typeof fields.description === 'string' ? fields.description : ''
  const head = `name:\t${name}\ndescription:\t${description}\n`
  return readme === null ? head : `${head}--\n${readme}`
}

/**
 * `gh repo view`. With `--json` it asks GraphQL for exactly the fields named,
 * the way gh does, so every field gh accepts is answered in gh's own shape;
 * the text view reads the REST object and the README.
 */
export async function view(inv: CLIInvocation): Promise<CommandFnResult> {
  const fl = new FlagView(inv.flags)
  const transport = ghTransport(inv.config)
  const ref = ghRepo(inv.config, inv.texts[0] ?? fl.asStr('repo'))
  const fields = jsonFields(fl, REPO_FIELDS)
  if (fields !== null) {
    const node = await repositoryFields(transport, ref, repoSelection(fields))
    return typedOut(exportedRepo(node, fields), fl, '', REPO_FIELDS)
  }
  const value = await viewRepo(transport, ref)
  return typedOut(value, fl, summary(value, await readReadme(transport, ref)), REPO_FIELDS)
}

/** `gh repo list`, over GraphQL for `--json` as `view` is. */
export async function listCmd(inv: CLIInvocation): Promise<CommandFnResult> {
  const fl = new FlagView(inv.flags)
  const transport = ghTransport(inv.config)
  const limit = fl.asInt('limit') ?? 30
  const fields = jsonFields(fl, REPO_FIELDS)
  if (fields !== null) {
    const nodes = await listRepositoryFields(transport, inv.texts[0], limit, repoSelection(fields))
    return typedOut(
      nodes.map((node) => exportedRepo(node, fields)),
      fl,
      '',
      REPO_FIELDS,
    )
  }
  const rows = (await listRepos(transport, inv.texts[0], limit)).map(repo)
  const human = rows
    .map(
      (row) =>
        `${textValue(row.nameWithOwner)}\t${textValue(row.description)}\t${textValue(row.visibility)}\t${textValue(row.updatedAt)}\n`,
    )
    .join('')
  return typedOut(rows, fl, human, REPO_FIELDS)
}

export async function createCmd(inv: CLIInvocation): Promise<CommandFnResult> {
  const fl = new FlagView(inv.flags)
  const spec = inv.texts[0] ?? ''
  if (spec === '') throw new Error('a repository name is required in noninteractive mode')
  const parts = spec.split('/')
  if (parts.length > 2 || parts.some((part) => part === '')) {
    throw new Error(`invalid repository name: "${spec}"`)
  }
  if (fl.asBool('public') && fl.asBool('private')) {
    throw new Error('--public and --private are mutually exclusive')
  }
  const owner = parts.length === 2 ? parts[0] : undefined
  const body: Record<string, unknown> = {
    name: parts.at(-1) ?? '',
    private: fl.asBool('private'),
    auto_init: fl.asBool('add_readme'),
  }
  const description = fl.asStr('description')
  const homepage = fl.asStr('homepage')
  if (description !== undefined) body.description = description
  if (homepage !== undefined) body.homepage = homepage
  const created = repo(await createRepo(ghTransport(inv.config), owner, body))
  return textOut(`${textValue(created.url)}\n`)
}

export async function fork(inv: CLIInvocation): Promise<CommandFnResult> {
  const fl = new FlagView(inv.flags)
  const transport = ghTransport(inv.config)
  const source = ghRepo(inv.config, inv.texts[0])
  const name = fl.asStr('fork_name') ?? undefined
  const forked = (await forkRepo(transport, source, name)) as { full_name?: string }
  const full = forked.full_name ?? `${await login(transport)}/${name ?? source.repo}`
  return textOut(`✓ Created fork ${full}\n`)
}

export async function rename(inv: CLIInvocation): Promise<CommandFnResult> {
  const fl = new FlagView(inv.flags)
  const transport = ghTransport(inv.config)
  // gh takes the *new name* as the operand and the repository to rename as
  // -R, which is the reverse of what the shape of the line suggests.
  const target = ghRepo(inv.config, fl.asStr('repo') ?? undefined)
  const name = inv.texts[0] ?? ''
  if (name === '') throw new Error('a new repository name is required')
  const renamed = (await renameRepo(transport, target, name)) as { full_name?: string }
  return textOut(`✓ Renamed repository ${renamed.full_name ?? name}\n`)
}
