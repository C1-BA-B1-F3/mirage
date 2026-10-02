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

import { pathSafeName } from '../../utils/sanitize.ts'
import { fileIdName, makeIdName } from '../../utils/naming.ts'
import type { SearchTarget } from './scope.ts'

const DEC = new TextDecoder('utf-8', { fatal: false })

/** Compute the VFS dirname for a channel, of the form `name__C123`. */
export function channelDirname(ch: { id: string; name?: string }): string {
  return makeIdName(ch.name ?? '', ch.id, true)
}

/** Compute the VFS dirname for a DM, of the form `username__D123`. */
export function dmDirname(
  dm: { id: string; user?: string },
  userMap: Record<string, string>,
): string {
  const uid = dm.user ?? ''
  const display = userMap[uid] ?? (uid === '' ? '' : uid)
  return makeIdName(display, dm.id, true)
}

/** Compute the VFS filename for a user, of the form `name__U123.json`. */
export function userFilename(u: { id: string; name?: string }): string {
  return makeIdName(u.name ?? '', u.id, true, '.json')
}

/**
 * Construct a stable VFS filename for a Slack file, of shape
 * `<stem>__<F-id>.<ext>`, named after `name` and else `title` (see
 * `fileIdName`).
 */
export function fileBlobName(file: { id?: string; name?: string; title?: string }): string {
  return fileIdName(file.id ?? '', file.name, file.title)
}

interface SearchMessageMatch {
  channel?: { name?: string; id?: string }
  ts?: string
  username?: string
  user?: string
  text?: string
}

interface SearchMessagePayload {
  messages?: { matches?: SearchMessageMatch[] }
}

interface SearchFileMatch {
  id?: string
  name?: string
  title?: string
  timestamp?: number | string
}

interface SearchFilesPayload {
  files?: { matches?: SearchFileMatch[] }
}

export function buildQuery(pattern: string, scope: SearchTarget): string {
  if (
    scope.container === 'channels' &&
    scope.channelName !== undefined &&
    scope.channelName !== ''
  ) {
    return `in:#${scope.channelName} ${pattern}`
  }
  if (scope.container === 'dms' && scope.channelName !== undefined && scope.channelName !== '') {
    return `in:@${scope.channelName} ${pattern}`
  }
  return pattern
}

function tsToDate(ts: string | number | undefined): string {
  if (ts === undefined) return ''
  const tsFloat = typeof ts === 'number' ? ts : Number.parseFloat(ts)
  if (!Number.isFinite(tsFloat)) return ''
  return new Date(tsFloat * 1000).toISOString().slice(0, 10)
}

export function formatGrepResults(raw: Uint8Array, scope: SearchTarget, prefix: string): string[] {
  const payload = JSON.parse(DEC.decode(raw)) as SearchMessagePayload
  const matches = payload.messages?.matches ?? []
  const lines: string[] = []
  for (const msg of matches) {
    const ch = msg.channel ?? {}
    const chName = ch.name ?? scope.channelName ?? ''
    const chId = ch.id ?? scope.channelId ?? ''
    const container = scope.container ?? 'channels'
    const dateStr = tsToDate(msg.ts ?? '0')
    // The dirname readdir emits, not a second spelling of it: the label's
    // byte budget depends on the id, so composing the pair here reported a
    // path that does not exist as soon as a long channel name was trimmed on
    // one side and not the other. It also sanitized where readdir keeps the
    // original spelling, so the two disagreed on any name carrying a space,
    // an apostrophe or an emoji -- DM directories, named after a user's
    // display name, hit that on far shorter strings than NAME_MAX.
    const dirname = chId !== '' ? channelDirname({ id: chId, name: chName }) : pathSafeName(chName)
    const path =
      dateStr !== ''
        ? `${prefix}/${container}/${dirname}/${dateStr}/chat.jsonl`
        : `${prefix}/${container}/${dirname}`
    const author = msg.username ?? msg.user ?? '?'
    const text = (msg.text ?? '').replaceAll('\n', ' ')
    lines.push(`${path}:[${author}] ${text}`)
  }
  return lines
}

export function formatFileGrepResults(
  raw: Uint8Array,
  scope: SearchTarget,
  prefix: string,
): string[] {
  const payload = JSON.parse(DEC.decode(raw)) as SearchFilesPayload
  const matches = payload.files?.matches ?? []
  const lines: string[] = []
  for (const f of matches) {
    const fid = f.id ?? ''
    const title = f.title ?? f.name ?? fid
    const blob = fileBlobName(f)
    const dateStr = tsToDate(f.timestamp)
    if (scope.channelId === undefined || scope.channelId === '') continue
    const chId = scope.channelId
    const chName = scope.channelName ?? ''
    const dirname = chName !== '' ? channelDirname({ id: chId, name: chName }) : chId
    const container = scope.container ?? 'channels'
    const path =
      dateStr !== ''
        ? `${prefix}/${container}/${dirname}/${dateStr}/files/${blob}`
        : `${prefix}/${container}/${dirname}/files/${blob}`
    lines.push(`${path}:[file] ${title}`)
  }
  return lines
}
