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

import { HttpGitHubTransport, type GitHubTransport } from '../../../../core/github/client.ts'
import type { GhConfig } from '../../../../core/github/config.ts'
import { parseRepo, type RepoRef } from '../../../../core/github/repo.ts'
import { jqRun } from '../../../../core/jq/index.ts'
import { PartialOutputError, UsageError } from '../../../errors.ts'
import type { FlagView } from '../../../spec/flag_view.ts'
import type { FlagValue } from '../../../spec/types.ts'
import { IOResult, materialize, type ByteSource } from '../../../../io/types.ts'
import { PathSpec } from '../../../../types.ts'
import { fsStrerror, isEnoent, isEnotdir } from '../../../../utils/errors.ts'
import { resolvePath } from '../../../../utils/path.ts'
import { compareCodePoints } from '../../../../utils/sort.ts'
import type { CommandFnResult } from '../../../config.ts'
import type { CLIInvocation } from '../../types.ts'

const ENC = new TextEncoder()

export function ghTransport(config: unknown): GitHubTransport {
  const cfg = config as GhConfig
  const opts: { token: string; baseUrl?: string } = { token: cfg.token }
  if (cfg.baseUrl !== undefined) opts.baseUrl = cfg.baseUrl
  return new HttpGitHubTransport(opts)
}

/**
 * The repository a line is about: the operand if it named one, the
 * install's own otherwise. gh resolves this from the current git remote,
 * which a workspace has no equivalent of, so the config carries it.
 */
export function ghRepo(config: unknown, spec: string | undefined): RepoRef {
  const named = spec ?? (config as GhConfig).repo
  if (named === undefined || named === '') {
    throw new Error('no repository given; pass one or set `repo` on the install')
  }
  return parseRepo(named)
}

// gh's exporter writes with Go's encoding/json, which escapes U+2028 and
// U+2029 where JSON.stringify writes them raw. Every other character comes
// out the same (Go 1.22 and later spell \b and \f short, as JSON.stringify
// does), `<`, `>` and `&` raw too, since gh turns HTML escaping off.
const SEPARATORS = /[\u{2028}\u{2029}]/gu

/** One value as gh's exporter prints it: Go's compact JSON. */
function goJson(value: unknown): string {
  return JSON.stringify(value).replace(
    SEPARATORS,
    (separator) => `\\u${separator.charCodeAt(0).toString(16)}`,
  )
}

/**
 * `--json` output as gh writes it where stdout is not a terminal, which in a
 * workspace it never is: one compact line.
 */
export function jsonOut(value: unknown): CommandFnResult {
  const text = value === null ? '' : `${goJson(value)}\n`
  const out: ByteSource = ENC.encode(text)
  return [out, new IOResult()]
}

export function textOut(text: string): CommandFnResult {
  const out: ByteSource = ENC.encode(text)
  return [out, new IOResult()]
}

export function repoFor(inv: CLIInvocation, fl: FlagView): RepoRef {
  return ghRepo(inv.config, fl.asStr('repo') ?? undefined)
}

export function repoNumber(
  inv: CLIInvocation,
  fl: FlagView,
  value: string | undefined,
  label: string,
  urlKind: 'issues' | 'pull',
): [RepoRef, number] {
  const raw = value ?? ''
  if (/^\d+$/.test(raw)) return [repoFor(inv, fl), Number(raw)]
  const match = /^https?:\/\/[^/]+\/([^/]+)\/([^/]+)\/(issues|pull)\/(\d+)\/?$/.exec(raw)
  if (match?.[3] !== urlKind) throw new Error(`a ${label} number is required`)
  return [parseRepo(`${match[1] ?? ''}/${match[2] ?? ''}`), Number(match[4])]
}

export function csvValues(values: readonly string[]): string[] {
  return values.flatMap((value) =>
    value
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean),
  )
}

export async function readCliFile(
  inv: CLIInvocation,
  raw: FlagValue,
  option: string,
): Promise<Uint8Array> {
  if (!(raw instanceof PathSpec) && typeof raw !== 'string') {
    throw new Error(`${option} expects a file`)
  }
  const path = raw instanceof PathSpec ? raw.rawPath : raw
  if (path === '-') {
    if (inv.stdin === null) throw new Error(`${option} needs standard input`)
    return materialize(inv.stdin)
  }
  const dispatch = inv.doors?.dispatch
  if (dispatch === undefined) throw new Error(`${option} needs a workspace to read files from`)
  const spec =
    raw instanceof PathSpec ? raw : PathSpec.fromStrPath(resolvePath(raw, inv.env.PWD ?? '/'))
  try {
    const [data] = await dispatch('read', spec)
    return await materialize(data as ByteSource)
  } catch (err) {
    const strerror = isEnoent(err) || isEnotdir(err) ? fsStrerror(err) : null
    if (strerror !== null) throw new Error(`read ${path}: ${strerror}`)
    throw err
  }
}

export async function bodyValue(
  inv: CLIInvocation,
  fl: FlagView,
  opts: { value?: string; file?: string; required?: boolean } = {},
): Promise<string | undefined> {
  const value = opts.value ?? 'body'
  const file = opts.file ?? 'body_file'
  const inline = fl.asStr(value)
  const source = fl.raw(file)
  const valueFlag = `--${value.replaceAll('_', '-')}`
  const fileFlag = `--${file.replaceAll('_', '-')}`
  if (inline !== undefined && source !== undefined) {
    throw new UsageError(`${valueFlag} and ${fileFlag} are mutually exclusive`)
  }
  if (inline !== undefined) return inline
  if (source !== undefined)
    return new TextDecoder().decode(await readCliFile(inv, source, fileFlag))
  if (opts.required === true) throw new Error(`${valueFlag} or ${fileFlag} is required`)
  return undefined
}

function camelKey(key: string): string {
  const [head = '', ...tail] = key.split('_')
  return head + tail.map((part) => part.slice(0, 1).toUpperCase() + part.slice(1)).join('')
}

export function camel(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(camel)
  if (value === null || typeof value !== 'object') return value
  const result: Record<string, unknown> = {}
  for (const [key, item] of Object.entries(value)) result[camelKey(key)] = camel(item)
  if ('htmlUrl' in result) {
    result.url = result.htmlUrl
    delete result.htmlUrl
  }
  if ('user' in result) {
    result.author = result.user
    delete result.user
  }
  return result
}

export function textValue(value: unknown): string {
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return ''
}

function jqLine(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'string') return value
  return JSON.stringify(value)
}

/**
 * Each row cut to the fields asked for, keys in sorted order: gh exports a
 * Go map, which its JSON encoder always writes sorted.
 */
function select(value: unknown, fields: string[]): unknown {
  const rows = Array.isArray(value) ? value : [value]
  const keys = [...new Set(fields)].sort(compareCodePoints)
  const selected = rows.map((row) => {
    const source = row !== null && typeof row === 'object' ? (row as Record<string, unknown>) : {}
    return Object.fromEntries(keys.map((field) => [field, source[field] ?? null]))
  })
  return Array.isArray(value) ? selected : selected[0]
}

/**
 * The `--json` fields a line asked for, null without `--json`.
 *
 * Checked before any request, as gh checks them: a field gh does not export
 * is refused with gh's own message and every field it does, sorted, exit 1.
 */
export function jsonFields(fl: FlagView, allowed: readonly string[]): string[] | null {
  const spelled = fl.asStr('json')
  if (spelled === undefined) return null
  const fields = csvValues([spelled])
  const listing = [...allowed].sort(compareCodePoints).map((field) => `  ${field}`)
  if (fields.length === 0) {
    throw new UsageError(
      ['Specify one or more comma-separated fields for `--json`:', ...listing].join('\n'),
      1,
    )
  }
  const known = new Set(allowed)
  const unknown = fields.find((field) => !known.has(field))
  if (unknown !== undefined) {
    throw new UsageError(
      [`Unknown JSON field: ${JSON.stringify(unknown)}`, 'Available fields:', ...listing].join(
        '\n',
      ),
      1,
    )
  }
  return fields
}

/**
 * The lines `--jq` prints for each value in turn, the way go-gh's jq
 * evaluates them. `halt`, and `halt_error` on null, end that value's output
 * there. An error, or any other `halt_error`, fails the command, the latter
 * as `halt error: <message>` whatever code it names, after the lines printed
 * before it: a PartialOutputError carries them.
 */
export async function jqLines(values: readonly unknown[], program: string): Promise<string> {
  const lines: string[] = []
  for (const value of values) {
    const run = await jqRun(value, program)
    for (const item of run.outputs) lines.push(`${jqLine(item)}\n`)
    let failure: string | null = null
    if (run.stop?.kind === 'error') failure = run.stop.text
    else if (run.stop?.kind === 'halt' && run.stop.message !== null) {
      failure = `halt error: ${run.stop.message}`
    }
    if (failure !== null) {
      throw new PartialOutputError(failure, new TextEncoder().encode(lines.join('')))
    }
  }
  return lines.join('')
}

export async function typedOut(
  value: unknown,
  fl: FlagView,
  human: string,
  allowed: readonly string[],
): Promise<CommandFnResult> {
  const program = fl.asStr('jq')
  const fields = jsonFields(fl, allowed)
  if (fields === null) {
    if (program !== undefined && program !== '') throw new UsageError('--jq requires --json')
    return textOut(human)
  }
  const selected = select(value, fields)
  if (program !== undefined && program !== '') {
    return textOut(await jqLines([selected], program))
  }
  return jsonOut(selected)
}
