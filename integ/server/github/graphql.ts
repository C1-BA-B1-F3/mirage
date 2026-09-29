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

import { buildSchema, graphql } from 'graphql'

import type { Ctx, JsonValue, KitRoute, Reply } from '../kit/typescript/index.ts'
import { DEFAULT_LOGIN } from './config.ts'
import type { C } from './config.ts'
import { authedRoute, everywhere, jsonBodyOf, route, str } from './http.ts'
import { issueOrPullRequestNode } from './issues.ts'
import { ownedRepositories, repositoryNode } from './repos.ts'
import { repoByName } from './store.ts'

// The slice of the vendor's schema the clients here send: issue and pull
// request comments, and every Repository field `gh repo view/list --json`
// selects, with the argument and enum spellings gh 2.85 puts on the wire.
const SCHEMA = buildSchema(`
  type Query {
    repository(owner: String!, name: String!): Repository
    repositoryOwner(login: String!): RepositoryOwner
    viewer: RepositoryOwner!
  }
  enum IssueState { OPEN CLOSED }
  enum PullRequestState { OPEN CLOSED MERGED }
  enum MilestoneState { OPEN CLOSED }
  enum ProjectState { OPEN CLOSED }
  enum RepositoryPrivacy { PUBLIC PRIVATE }
  enum RepositoryAffiliation { OWNER COLLABORATOR ORGANIZATION_MEMBER }
  enum RepositoryOrderField { CREATED_AT UPDATED_AT PUSHED_AT NAME STARGAZERS }
  enum OrderDirection { ASC DESC }
  input RepositoryOrder { field: RepositoryOrderField!, direction: OrderDirection! }
  type RepositoryOwner {
    login: String!
    repositories(first: Int!, after: String, privacy: RepositoryPrivacy, isFork: Boolean,
      ownerAffiliations: [RepositoryAffiliation], orderBy: RepositoryOrder): RepositoryConnection!
  }
  type RepositoryConnection { nodes: [Repository!]!, totalCount: Int!, pageInfo: PageInfo! }
  type Owner { id: ID!, login: String! }
  type Count { totalCount: Int! }
  type Ref { name: String! }
  type CodeOfConduct { key: String!, name: String!, url: String }
  type ContactLink { about: String!, name: String!, url: String! }
  type FundingLink { platform: String!, url: String! }
  type License { key: String!, name: String!, nickname: String }
  type Topic { name: String! }
  type TopicNode { topic: Topic! }
  type TopicConnection { nodes: [TopicNode!]! }
  type Language { name: String! }
  type LanguageEdge { size: Int!, node: Language! }
  type LanguageConnection { edges: [LanguageEdge!]! }
  type IssueTemplate { name: String!, title: String, body: String, about: String }
  type PullRequestTemplate { body: String, filename: String }
  type Label { id: ID!, color: String!, name: String!, description: String }
  type LabelConnection { nodes: [Label!]! }
  type Milestone { number: Int!, title: String!, description: String, dueOn: String }
  type MilestoneConnection { nodes: [Milestone!]! }
  type Release { publishedAt: String, tagName: String!, name: String, url: String! }
  type User { id: ID!, login: String!, name: String }
  type UserConnection { nodes: [User!]! }
  type Project { id: ID!, name: String!, number: Int!, body: String, resourcePath: String! }
  type ProjectConnection { nodes: [Project!]! }
  type ProjectV2 { id: ID!, number: Int!, title: String!, resourcePath: String!,
    closed: Boolean!, url: String! }
  type ProjectV2Connection { nodes: [ProjectV2!]! }
  type Repository {
    id: ID!
    name: String!
    nameWithOwner: String!
    owner: Owner!
    parent: Repository
    templateRepository: Repository
    description: String
    homepageUrl: String
    openGraphImageUrl: String!
    usesCustomOpenGraphImage: Boolean!
    url: String!
    sshUrl: String!
    mirrorUrl: String
    securityPolicyUrl: String
    createdAt: String!
    pushedAt: String
    updatedAt: String!
    archivedAt: String
    isBlankIssuesEnabled: Boolean!
    isSecurityPolicyEnabled: Boolean
    hasIssuesEnabled: Boolean!
    hasProjectsEnabled: Boolean!
    hasDiscussionsEnabled: Boolean!
    hasWikiEnabled: Boolean!
    mergeCommitAllowed: Boolean!
    squashMergeAllowed: Boolean!
    rebaseMergeAllowed: Boolean!
    forkCount: Int!
    stargazerCount: Int!
    watchers: Count!
    issues(states: [IssueState!]): Count!
    pullRequests(states: [PullRequestState!]): Count!
    codeOfConduct: CodeOfConduct
    contactLinks: [ContactLink!]
    defaultBranchRef: Ref
    deleteBranchOnMerge: Boolean!
    diskUsage: Int
    fundingLinks: [FundingLink!]!
    isArchived: Boolean!
    isEmpty: Boolean!
    isFork: Boolean!
    isInOrganization: Boolean!
    isMirror: Boolean!
    isPrivate: Boolean!
    isTemplate: Boolean!
    isUserConfigurationRepository: Boolean!
    licenseInfo: License
    viewerCanAdminister: Boolean!
    viewerDefaultCommitEmail: String
    viewerDefaultMergeMethod: String!
    viewerHasStarred: Boolean!
    viewerPermission: String
    viewerPossibleCommitEmails: [String!]
    viewerSubscription: String
    visibility: String!
    repositoryTopics(first: Int!): TopicConnection!
    primaryLanguage: Language
    languages(first: Int): LanguageConnection
    issueTemplates: [IssueTemplate!]
    pullRequestTemplates: [PullRequestTemplate!]
    labels(first: Int): LabelConnection
    milestones(first: Int, states: [MilestoneState!]): MilestoneConnection
    latestRelease: Release
    assignableUsers(first: Int): UserConnection!
    mentionableUsers(first: Int): UserConnection!
    projects(first: Int, states: [ProjectState!]): ProjectConnection!
    projectsV2(first: Int, query: String): ProjectV2Connection!
    issueOrPullRequest(number: Int!): IssueOrPullRequest
  }
  union IssueOrPullRequest = Issue | PullRequest
  type Issue { comments(first: Int!, after: String): IssueCommentConnection! }
  type PullRequest { comments(first: Int!, after: String): IssueCommentConnection! }
  type IssueCommentConnection { nodes: [IssueComment!]!, pageInfo: PageInfo! }
  type PageInfo { hasNextPage: Boolean!, endCursor: String }
  type Actor { login: String! }
  type Users { totalCount: Int! }
  type ReactionGroup { content: String!, users: Users! }
  type IssueComment {
    id: ID!, author: Actor, authorAssociation: String!, body: String!,
    createdAt: String!, includesCreatedEdit: Boolean!, isMinimized: Boolean!,
    minimizedReason: String, reactionGroups: [ReactionGroup!]!, url: String!,
    viewerDidAuthor: Boolean!
  }
`)

/**
 * Answer one GraphQL request against the fake's rows.
 *
 * A repository that does not exist is an error on its field, worded and
 * located as the vendor words it, rather than a quiet null: that is what a
 * client sees live, and what `gh` turns into
 * `GraphQL: Could not resolve to a Repository with the name 'o/r'. (repository)`.
 */
async function answer(ctx: Ctx<C>): Promise<Reply> {
  const body = jsonBodyOf(ctx)
  const result = await graphql({
    schema: SCHEMA,
    source: str(body, 'query'),
    variableValues: body.variables as Record<string, unknown> | undefined,
    rootValue: {
      repository: async ({ owner, name }: { owner: string; name: string }) => {
        const repo = await repoByName(ctx.db, ctx.tenant, `${owner}/${name}`)
        if (repo === null) {
          throw new Error(`Could not resolve to a Repository with the name '${owner}/${name}'.`)
        }
        return {
          ...(await repositoryNode(ctx, repo)),
          issueOrPullRequest: ({ number }: { number: number }) =>
            issueOrPullRequestNode(ctx, repo, number),
        }
      },
      repositoryOwner: ({ login }: { login: string }) => ownedRepositories(ctx, login),
      viewer: () => ownedRepositories(ctx, DEFAULT_LOGIN),
    },
  })
  return { status: 200, body: JSON.parse(JSON.stringify(result)) as JsonValue }
}

export function graphqlRoutes(): KitRoute<C>[] {
  return everywhere<C>(['', '/api'], (p) => [route<C>('POST', `${p}/graphql`, authedRoute(answer))])
}
