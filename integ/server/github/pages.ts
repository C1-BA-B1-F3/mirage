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

import type { Ctx, JsonValue, KitRoute, Reply } from '../kit/typescript/index.ts'
import { API_PREFIXES } from './config.ts'
import type { C } from './config.ts'
import { branchFor, metaOf } from './store.ts'
import type { RepoRow } from './store.ts'
import { authedRoute, everywhere, fail, jsonBodyOf, route, withRepo } from './http.ts'

// A repository's GitHub Pages site, as the Pages endpoints set it. The fake
// builds nothing, so a site reads as built from the moment it exists.
interface Site {
  build_type: string
  source: { branch: string; path: string }
  cname: string | null
  https_enforced: boolean
}

const BUILD_TYPES = ['legacy', 'workflow']
const SOURCE_PATHS = ['/', '/docs']

function siteOf(repo: RepoRow): Site | null {
  return repo.pagesJson === '' ? null : (JSON.parse(repo.pagesJson) as Site)
}

// `<owner>.github.io` is the owner's own site, served at the root; any other
// repository's is served under its name.
function siteUrl(repo: RepoRow): string {
  const host = `${repo.owner.toLowerCase()}.github.io`
  return repo.name.toLowerCase() === host ? `https://${host}/` : `https://${host}/${repo.name}/`
}

function siteJson(repo: RepoRow, site: Site): JsonValue {
  return {
    url: `https://api.github.com/repos/${repo.fullName}/pages`,
    status: 'built',
    cname: site.cname,
    custom_404: false,
    html_url: siteUrl(repo),
    build_type: site.build_type,
    source: site.source,
    public: metaOf(repo).private !== true,
    protected_domain_state: null,
    pending_domain_unverified_at: null,
    https_enforced: site.https_enforced,
  }
}

async function store(ctx: Ctx<C>, repo: RepoRow, site: Site | null): Promise<void> {
  await ctx.db.githubRepo.update({
    where: { tenant_fullName: { tenant: ctx.tenant, fullName: repo.fullName } },
    data: { pagesJson: site === null ? '' : JSON.stringify(site) },
  })
}

// The site a body asks for on top of `base`, or null when any field it names
// is not one GitHub takes: a build type it does not know, a source whose
// branch the repository lacks or whose path is neither the root nor /docs.
async function edited(
  ctx: Ctx<C>,
  repo: RepoRow,
  base: Site,
  body: Record<string, JsonValue>,
): Promise<Site | null> {
  const site = { ...base, source: { ...base.source } }
  if (body.build_type !== undefined) {
    if (typeof body.build_type !== 'string' || !BUILD_TYPES.includes(body.build_type)) return null
    site.build_type = body.build_type
  }
  if (body.source !== undefined) {
    const source = body.source
    if (typeof source !== 'object' || source === null || Array.isArray(source)) return null
    const branch = typeof source.branch === 'string' ? source.branch : ''
    if (branch === '' || (await branchFor(ctx.db, ctx.tenant, repo, branch)) === null) return null
    const path = source.path ?? '/'
    if (typeof path !== 'string' || !SOURCE_PATHS.includes(path)) return null
    site.source = { branch, path }
  }
  if (body.cname !== undefined) {
    if (body.cname !== null && typeof body.cname !== 'string') return null
    site.cname = body.cname === '' ? null : body.cname
  }
  if (body.https_enforced !== undefined) {
    if (typeof body.https_enforced !== 'boolean') return null
    site.https_enforced = body.https_enforced
  }
  return site
}

async function getSite(_ctx: Ctx<C>, repo: RepoRow): Promise<Reply> {
  const site = siteOf(repo)
  return site === null ? fail(404, 'Not Found') : { status: 200, body: siteJson(repo, site) }
}

// Creating a site takes a source unless the site is built by a workflow,
// which publishes whatever it deploys; one per repository.
async function createSite(ctx: Ctx<C>, repo: RepoRow): Promise<Reply> {
  if (siteOf(repo) !== null) return fail(409, 'GitHub Pages is already enabled.')
  const body = jsonBodyOf(ctx)
  const base: Site = {
    build_type: 'legacy',
    source: { branch: repo.defaultBranch, path: '/' },
    cname: null,
    https_enforced: true,
  }
  const site = await edited(ctx, repo, base, body)
  if (site === null || (site.build_type === 'legacy' && body.source === undefined)) {
    return fail(422, 'Validation Failed')
  }
  await store(ctx, repo, site)
  return { status: 201, body: siteJson(repo, site) }
}

async function updateSite(ctx: Ctx<C>, repo: RepoRow): Promise<Reply> {
  const current = siteOf(repo)
  if (current === null) return fail(404, 'Not Found')
  const site = await edited(ctx, repo, current, jsonBodyOf(ctx))
  if (site === null) return fail(422, 'Validation Failed')
  await store(ctx, repo, site)
  return { status: 204 }
}

async function deleteSite(ctx: Ctx<C>, repo: RepoRow): Promise<Reply> {
  if (siteOf(repo) === null) return fail(404, 'Not Found')
  await store(ctx, repo, null)
  return { status: 204 }
}

export function pageRoutes(): KitRoute<C>[] {
  return everywhere<C>(API_PREFIXES, (p) => {
    const pages = `${p}/repos/:owner/:repo/pages`
    return [
      route<C>('GET', pages, authedRoute(withRepo(getSite))),
      route<C>('POST', pages, authedRoute(withRepo(createSite)), { write: true }),
      route<C>('PUT', pages, authedRoute(withRepo(updateSite)), { write: true }),
      route<C>('DELETE', pages, authedRoute(withRepo(deleteSite)), { write: true }),
    ]
  })
}
