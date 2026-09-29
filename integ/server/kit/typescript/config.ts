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

import { KitError } from './errors.ts'
import type { MintSharing, TenantKind } from './types.ts'

export interface KitConfig {
  service: string
  defaultPort: number
  schema: string
  tenantKind: TenantKind
  tenantFromBearer: boolean
  tenantTokenPattern: string
  runTokenPattern: string
  mintSharing: MintSharing
  mintFormat: string
  maxBodyBytes: number
}

const DEFAULTS = {
  defaultPort: 0,
  tenantKind: 'none' as TenantKind,
  tenantFromBearer: false,
  tenantTokenPattern: '',
  runTokenPattern: process.env.MIRAGE_RUN_TOKEN_PATTERN ?? '',
  mintSharing: 'global' as MintSharing,
  mintFormat: '{kind}_new_{n}',
  maxBodyBytes: 64 * 1024 * 1024,
}

const REQUIRED = ['service', 'schema'] as const
const KNOWN = new Set<string>([...Object.keys(DEFAULTS), ...REQUIRED])

export function parseConfig(raw: Record<string, unknown>): KitConfig {
  const unknown = Object.keys(raw).filter((k) => !KNOWN.has(k))
  if (unknown.length > 0) {
    throw new KitError(`unknown KitConfig fields: ${unknown.sort().join(', ')}`)
  }
  for (const k of REQUIRED) {
    if (typeof raw[k] !== 'string' || raw[k] === '') {
      throw new KitError(`KitConfig.${k} is required`)
    }
  }
  const pattern = raw.runTokenPattern === undefined ? DEFAULTS.runTokenPattern : raw.runTokenPattern
  if (typeof pattern !== 'string') throw new KitError('KitConfig.runTokenPattern must be a string')
  if (pattern !== '') {
    try {
      new RegExp(pattern)
    } catch {
      throw new KitError('KitConfig.runTokenPattern must be a valid regular expression')
    }
    const groups = new RegExp(`(?:${pattern})|`).exec('')?.groups
    if (groups === undefined || !Object.hasOwn(groups, 'run')) {
      throw new KitError('KitConfig.runTokenPattern needs a named run capture')
    }
  }
  return {
    ...DEFAULTS,
    ...raw,
    runTokenPattern: pattern,
    service: raw.service as string,
    schema: raw.schema as string,
  }
}
