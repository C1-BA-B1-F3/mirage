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

import { apiRequest } from '@struktoai/mirage-core/core/api/client'
import type { ApiResponse, RetryPolicy } from '@struktoai/mirage-core/core/api/client'
import type { ByteWindow } from '@struktoai/mirage-core/utils/ranges'
import { API_SEGMENTS, MAX_RETRIES, RESOLVE_SEGMENTS, RETRY_STATUSES } from './constants.ts'
import { rstripSlash } from '@struktoai/mirage-core/utils/slash'

export const RETRY: RetryPolicy = {
  statuses: RETRY_STATUSES,
  maxRetries: MAX_RETRIES,
  maxBackoff: 30,
  delaySource: 'header',
  retryTransport: true,
}

/** A Hub call that answered with a status the caller cannot use. */
export class HfHubError extends Error {
  /**
   * The Hub's `X-Error-Code`, '' when it sent none. The status alone cannot
   * tell its refusals apart: a missing repository, a missing revision and a
   * missing file are all 404, and only this header says which
   * (`RepoNotFound` / `RevisionNotFound` / `EntryNotFound`).
   */
  readonly errorCode: string

  constructor(message: string, status: number, errorCode = '') {
    super(message)
    this.name = 'HfHubError'
    this.status = status
    this.errorCode = errorCode
  }

  readonly status: number
}

/**
 * Auth and accept headers for one Hub call.
 *
 * An anonymous call is a first-class case here, unlike GitHub's: the Hub
 * serves every public repo without a token, so a mount with no credential
 * reads normally and only the write path needs one.
 */
export function hubHeaders(token: string | undefined): Record<string, string> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (token !== undefined && token !== '') headers.Authorization = `Bearer ${token}`
  return headers
}

/** The /api URL for one repository-scoped endpoint. */
export function apiUrl(endpoint: string, repoType: string, repoId: string, suffix: string): string {
  const segment = API_SEGMENTS[repoType] ?? 'models'
  return `${rstripSlash(endpoint)}/api/${segment}/${repoId}${suffix}`
}

/**
 * The content URL for one file at one revision.
 *
 * The path is percent-encoded per segment: a Hub repo may hold a file whose
 * name carries a space or a "#", and pasting it raw truncates the URL at the
 * fragment.
 */
/**
 * The web URL of a repository, which is what the CLI echoes.
 *
 * A model sits at the origin root and the other two kinds sit under a
 * plural segment, the same split `resolveUrl` walks.
 */
/**
 * One revision, encoded as a single URL path segment.
 *
 * A git ref may hold a slash (`feature/foo`, `refs/pr/1`), and every Hub
 * route reads the segment after the verb as the whole revision, so an
 * unencoded one splits: `/tree/feature/foo` names revision `feature` and
 * subtree `foo`. The extra replace is what makes this identical to
 * python's `quote(revision, safe="")`, which encodes the four characters
 * `encodeURIComponent` leaves alone.
 */
export function revSegment(revision: string): string {
  return encodeURIComponent(revision).replace(
    /[!'()*]/g,
    (c) => `%${c.charCodeAt(0).toString(16).toUpperCase()}`,
  )
}

export function repoUrl(endpoint: string, repoType: string, repoId: string): string {
  const segment = RESOLVE_SEGMENTS[repoType] ?? ''
  const base = `${rstripSlash(endpoint)}/${segment === '' ? '' : `${segment}/`}`
  return `${base}${repoId}`
}

export function resolveUrl(
  endpoint: string,
  repoType: string,
  repoId: string,
  revision: string,
  path: string,
): string {
  const segment = RESOLVE_SEGMENTS[repoType] ?? ''
  const base = `${rstripSlash(endpoint)}/${segment === '' ? '' : `${segment}/`}`
  const encoded = path
    .replace(/^\/+/, '')
    .split('/')
    .map((part) => encodeURIComponent(part))
    .join('/')
  return `${base}${repoId}/resolve/${revSegment(revision)}/${encoded}`
}

/**
 * Map a failing Hub response to the backend's own error.
 *
 * The Hub reports its reason in an `X-Error-Message` header as well as in the
 * body, and the header is the one that survives a HEAD, so it is preferred.
 */
export function errorOf(response: Response, text: string): Error {
  const header = response.headers.get('X-Error-Message')
  const message = header ?? text.trim()
  const fallback = response.statusText === '' ? 'request failed' : response.statusText
  return new HfHubError(
    message === '' ? fallback : message,
    response.status,
    response.headers.get('X-Error-Code') ?? '',
  )
}

export async function hubGet(
  token: string | undefined,
  url: string,
  params?: Record<string, string>,
): Promise<unknown> {
  return apiRequest('GET', url, {
    errorOf,
    headers: hubHeaders(token),
    params,
    retry: RETRY,
  })
}

/** One GET retaining status and headers, which tree pagination reads. */
export async function hubGetResponse(
  token: string | undefined,
  url: string,
  params?: Record<string, string>,
): Promise<ApiResponse> {
  return (await apiRequest('GET', url, {
    errorOf,
    headers: hubHeaders(token),
    params,
    retry: RETRY,
    read: 'response',
  })) as ApiResponse
}

export async function hubPost(
  token: string | undefined,
  url: string,
  body: unknown,
  params?: Record<string, string>,
): Promise<unknown> {
  // fetch labels an untyped string body text/plain, and the Hub answers a
  // paths-info body without a JSON type with 400; python's aiohttp sets it.
  return apiRequest('POST', url, {
    errorOf,
    headers: { ...hubHeaders(token), 'Content-Type': 'application/json' },
    params,
    json: body,
    retry: RETRY,
  })
}

/** One arbitrary JSON call, for the endpoints that are not GET or POST. */
export async function hubRequest(
  token: string | undefined,
  method: string,
  url: string,
  body: unknown,
  params?: Record<string, string>,
): Promise<unknown> {
  const options: Parameters<typeof apiRequest>[2] = {
    errorOf,
    headers: hubHeaders(token),
    params,
    retry: RETRY,
  }
  if (body !== null && body !== undefined) options.json = body
  return apiRequest(method.toUpperCase(), url, options)
}

/** One newline-delimited-JSON POST, which is the commit endpoint's shape. */
export async function hubPostNdjson(
  token: string | undefined,
  url: string,
  payload: Uint8Array,
  params?: Record<string, string>,
): Promise<unknown> {
  return apiRequest('POST', url, {
    errorOf,
    headers: { ...hubHeaders(token), 'Content-Type': 'application/x-ndjson' },
    params,
    body: payload,
    retry: RETRY,
  })
}

/**
 * Fetch file content, optionally a byte window of it.
 *
 * `/resolve` answers a redirect to the CDN and fetch follows it, carrying the
 * Range along, so a window costs no extra round trip.
 */
export async function hubBytes(
  token: string | undefined,
  url: string,
  window?: ByteWindow,
): Promise<Uint8Array> {
  return (await apiRequest('GET', url, {
    errorOf,
    headers: hubHeaders(token),
    retry: RETRY,
    read: 'bytes',
    window,
  })) as Uint8Array
}

/**
 * Fetch file content together with the ETag the bytes came with.
 *
 * The ETag is the final response's, after the redirect to the CDN: the first
 * hop answers for the LFS object, the last one for the bytes actually served,
 * which is the only one that can vouch for them. The ETag is `''` when none.
 */
export async function hubBytesTagged(
  token: string | undefined,
  url: string,
  window?: ByteWindow,
): Promise<[Uint8Array, string]> {
  const response = (await apiRequest('GET', url, {
    errorOf,
    headers: hubHeaders(token),
    retry: RETRY,
    read: 'bytes_response',
    window,
  })) as ApiResponse
  return [response.data as Uint8Array, response.headers.etag ?? '']
}

/** An ETag header's value, without the weak marker or the quotes. */
export function etagValue(raw: string): string {
  let value = raw.trim()
  if (value.startsWith('W/')) value = value.slice(2)
  return value.replace(/^"+|"+$/g, '')
}

/**
 * Stream file content without holding it whole in memory.
 *
 * Not routed through `apiRequest`: that reads the body to completion before
 * returning, which is the opposite of what a stream is for. `onResponse` is
 * told the final response's headers, lower-cased, once and before the first
 * chunk, so an empty file reports them too.
 */
export async function* hubStream(
  token: string | undefined,
  url: string,
  onResponse?: (headers: Record<string, string>) => void,
): AsyncIterable<Uint8Array> {
  const response = await fetch(url, { headers: hubHeaders(token) })
  if (response.status >= 400) throw errorOf(response, await response.text())
  if (onResponse !== undefined) {
    const headers: Record<string, string> = {}
    response.headers.forEach((value, name) => {
      headers[name.toLowerCase()] = value
    })
    onResponse(headers)
  }
  const body = response.body
  if (body === null) return
  const reader = body.getReader()
  for (;;) {
    const chunk = await reader.read()
    if (chunk.done) break
    if (chunk.value !== undefined) yield chunk.value
  }
}
