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

import { existsSync, readdirSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { defaultProvision } from '@struktoai/mirage-core/commands/builtin/generic_bind/index'
import type { RegisteredCommand } from '@struktoai/mirage-core/commands/config'
import type { FileStat } from '@struktoai/mirage-core/types'

// The node half of the provision gate; core pins its own backends in
// generic_bind/provision.test.ts and python every package in
// tests/commands/builtin/generic_bind/test_provision.py. A backend that
// shadows a generic builder with its own command drops the builder's
// provision unless it wraps the command in withDefaultProvisions.
function stat(): Promise<FileStat> {
  return Promise.reject(new Error('the gate only asks whether a provision exists'))
}

describe('node backend commands keep their catalog provision', () => {
  it('every command the catalog prices carries a provision', async () => {
    const offenders: string[] = []
    let lists = 0
    for (const entry of readdirSync(import.meta.dirname).sort()) {
      const index = join(import.meta.dirname, entry, 'index.ts')
      if (!existsSync(index)) continue
      const mod = (await import(index)) as Record<string, unknown>
      for (const [name, value] of Object.entries(mod)) {
        if (!name.endsWith('_COMMANDS') || !Array.isArray(value)) continue
        lists += 1
        for (const c of value as RegisteredCommand[]) {
          if (c.filetype !== null || c.provisionFn !== null) continue
          if (defaultProvision(c.name, stat) !== null) offenders.push(`${entry}: ${c.name}`)
        }
      }
    }
    expect(lists).toBeGreaterThan(5)
    expect(offenders).toEqual([])
  })
})
