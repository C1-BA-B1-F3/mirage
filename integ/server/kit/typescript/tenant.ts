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

import { randomUUID } from 'node:crypto'
import type { KitConfig } from './config.ts'
import { TenantError } from './errors.ts'
import type { JsonValue, TenantKind } from './types.ts'

export const RUN_HEADER = 'x-mirage-run'
export const TENANT_HEADER = 'x-mirage-tenant'
export const RUN_QUERY = '_run'
export const TENANT_QUERY = '_tenant'
export const RUN_PREFIX = '_run'
export const DEFAULT_RUN = 'default'
export const DEFAULT_TENANT = 'default'
export const TENANT_FIELD = 'tenant'

const NAME_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/

export type Headers = Record<string, string | string[] | undefined>

// Python mints run ids as uuid4().hex[:8]; TypeScript minted `${pid}-${now}`,
// which is a different alphabet and a different length. That id lands in
// bucket and collection names, so the two hosts were not naming the same
// things. One spelling, both languages.
export function runId(): string {
  return randomUUID().replace(/-/g, '').slice(0, 8)
}

function headerValue(headers: Headers, name: string): string | undefined {
  const raw = headers[name]
  if (raw === undefined) return undefined
  const one = Array.isArray(raw) ? raw[0] : raw
  return one === undefined || one === '' ? undefined : one
}

function bearer(headers: Headers): string | undefined {
  const auth = headerValue(headers, 'authorization')
  if (auth === undefined) return undefined
  const m = /^Bearer\s+(\S+)$/i.exec(auth)
  return m === null ? undefined : m[1]
}

export function checkName(kind: string, value: string): string {
  if (!NAME_RE.test(value)) throw new TenantError(`invalid ${kind} name: ${JSON.stringify(value)}`)
  return value
}

// decodeURIComponent throws a URIError on a malformed escape (`/_run/%ZZ`),
// which is caller-controlled input and so must arrive as the same 400 an
// illegal NAME gets. Left as a URIError it reached the internal 500 envelope,
// which reports a fake bug for a typed URL.
function decodeRun(raw: string): string {
  try {
    return decodeURIComponent(raw)
  } catch {
    throw new TenantError(`invalid run name: ${JSON.stringify(raw)}`)
  }
}

// The run also rides the URL, as a LEADING PATH SEGMENT, and that is the
// spelling a harness can actually use. The header and the query parameter are
// only reachable by a caller that builds its own requests; every mount here
// hands its base URL to a vendor SDK and never sees the request again, so
// neither survives the trip. A path prefix does, because it is just part of
// the base URL: `http://host/_run/<id>/v1` needs nothing of the client.
// Returns the run it stripped, if any, and the path the router should match.
export function splitRunPath(pathname: string): { run?: string; path: string } {
  const parts = pathname.split('/')
  if (parts.length < 3 || parts[1] !== RUN_PREFIX) return { path: pathname }
  const run = checkName('run', decodeRun(parts[2] ?? ''))
  const rest = parts.slice(3).join('/')
  return { run, path: rest === '' ? '/' : `/${rest}` }
}

// A run is its own SQLite file, so it is resolved before any query runs
// and never reaches a WHERE clause. The path segment wins over the header and
// the query because it is the one a mount can carry, so a base URL naming a
// run cannot be overridden by an ambient header the caller forgot to drop.
export function resolveRun(
  headers: Headers,
  url: URL,
  fromPath?: string,
  fromToken?: string,
): string {
  if (fromPath !== undefined) return fromPath
  const raw = headerValue(headers, RUN_HEADER) ?? url.searchParams.get(RUN_QUERY) ?? undefined
  return raw === undefined || raw === ''
    ? fromToken === undefined
      ? DEFAULT_RUN
      : checkName('run', fromToken)
    : checkName('run', raw)
}

// A tenant is a column inside one run file. The bearer fallback is what
// lets a fake whose vendor partitions by token (notion's workspace) keep
// answering on its real header instead of growing a mirage-only one, and it is
// OPT-IN per fake rather than implied by `pk-column`. Reading it from every
// pk-column fake meant an ordinary `Authorization: Bearer <token>` silently
// selected an unseeded tenant and every read 404'd, which is a worse answer
// than the 401 the real vendor gives: trello and linear are partitioned by the
// mount, not by the token, and neither has any use for it.
// A vendor whose token carries an ACTOR TYPE in front of the install identity
// needs the type stripped before the rest can name a tenant. Slack is the case:
// one workspace is reached with `xoxb-<id>` for most methods and `xoxp-<id>`
// for search.*, so using the raw bearer would split one workspace across two
// tenants and every search would read an empty one. The pattern's first capture
// group is the tenant; a token that does not match falls back to the default,
// exactly as an illegal one does.
export function tenantFromToken(token: string, pattern: string): string | undefined {
  if (pattern === '') return token
  const m = new RegExp(pattern).exec(token)
  return m === null ? undefined : m[1]
}

export function resolveTenant(
  headers: Headers,
  url: URL,
  kind: TenantKind,
  fromBearer = false,
  tokenPattern = '',
  requestToken?: string,
  credentialTenant?: string,
): string {
  if (kind === 'none') return DEFAULT_TENANT
  const named =
    headerValue(headers, TENANT_HEADER) ?? url.searchParams.get(TENANT_QUERY) ?? undefined
  if (named !== undefined && named !== '') return checkName('tenant', named)
  if (credentialTenant !== undefined) return checkName('tenant', credentialTenant)
  if (!fromBearer) return DEFAULT_TENANT
  // The bearer is a FALLBACK, not a request. A caller that spells the mirage
  // header or the query parameter has asked for a tenant and gets told when the
  // name is illegal; a vendor auth header that happens to be a Bearer has asked
  // for nothing, so a token that is not a legal name selects the default rather
  // than failing the request. Throwing here reached the 500 envelope from
  // OUTSIDE the reset try/catch, so `Authorization: Bearer a/b` answered 500 on
  // every route of every pk-column fake, where the fakes it replaces answered
  // their own 401.
  const raw = bearer(headers) ?? requestToken
  if (raw === undefined) return DEFAULT_TENANT
  const token = tenantFromToken(raw, tokenPattern)
  return token !== undefined && NAME_RE.test(token) ? token : DEFAULT_TENANT
}

// Opt-in credential transport: named captures keep the private run separate
// from a vendor-visible tenant. Explicit path/header/query selectors win.
export function resolveIdentity(
  config: KitConfig,
  headers: Headers,
  url: URL,
  fromPath?: string,
  requestToken?: string,
): { run: string; tenant: string } {
  const auth = headerValue(headers, 'authorization')
  const token = /^(?:Bearer|token)\s+(\S+)$/i.exec(auth ?? '')?.[1] ?? requestToken
  const groups =
    config.runTokenPattern === '' || token === undefined
      ? undefined
      : new RegExp(config.runTokenPattern).exec(token)?.groups
  return {
    run: resolveRun(headers, url, fromPath, groups?.run),
    tenant: resolveTenant(
      headers,
      url,
      config.tenantKind,
      config.tenantFromBearer,
      config.tenantTokenPattern,
      requestToken,
      groups?.tenant,
    ),
  }
}

// The pk-column mechanism, in three helpers so no fake spells a compound key
// by hand. A bare `@id` plus a plain tenant column collides across tenants
// (P2002 on the second tenant seeding the same fixture ids), which is why the
// column has to participate in @@id and therefore in every point lookup.
// Both are generic in their RETURN type, defaulting to the plain shape. A
// generated Prisma `WhereUniqueInput` for a compound @@id is a REQUIRED
// property, not an index signature, so a fixed Record return does not overlap
// with it at all and a point lookup would have to be written
// `as unknown as Prisma.XWhereUniqueInput` -- a double cast, which is exactly
// the spelling that stops reporting a wrong key name. The type argument is
// passed explicitly (`idWhere<Prisma.CardWhereUniqueInput>(...)`), because a
// contextual type does not reach here through Prisma's own generic
// findUnique/delete call. tenantWhere usually needs no argument: a
// `WhereInput` is all-optional, so the default shape already fits.
export function tenantWhere<W = Record<string, JsonValue>>(tenant: string, kind: TenantKind): W {
  const out: Record<string, JsonValue> = kind === 'none' ? {} : { [TENANT_FIELD]: tenant }
  return out as W
}

export function tenantKeyName(idField = 'id'): string {
  return `${TENANT_FIELD}_${idField}`
}

export function idWhere<W = Record<string, JsonValue>>(
  tenant: string,
  id: string,
  kind: TenantKind,
  idField = 'id',
): W {
  const out: Record<string, JsonValue> =
    kind === 'none'
      ? { [idField]: id }
      : { [tenantKeyName(idField)]: { [TENANT_FIELD]: tenant, [idField]: id } }
  return out as W
}
