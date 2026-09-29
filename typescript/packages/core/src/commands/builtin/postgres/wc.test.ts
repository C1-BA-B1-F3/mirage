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

import { mountKey } from '../../../utils/key_prefix.ts'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../../core/postgres/client.ts', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  countRows: vi.fn(),
  listSchemas: vi.fn(),
  listTables: vi.fn(),
}))

import { PostgresAccessor } from '../../../accessor/postgres.ts'
import type { PgDriver, PgQueryResult } from '../../../core/postgres/_driver.ts'
import * as clientModule from '../../../core/postgres/client.ts'
import { resolvePostgresConfig } from '../../../vfs/postgres/config.ts'
import { PathSpec } from '../../../types.ts'
import { materialize } from '../../../io/types.ts'
import { POSTGRES_WC } from './wc.ts'

class StubDriver implements PgDriver {
  query<R = Record<string, unknown>>(): Promise<PgQueryResult<R>> {
    return Promise.resolve({ rows: [] as R[], rowCount: 0 })
  }
  close(): Promise<void> {
    return Promise.resolve()
  }
}

function rows(schema: string): PathSpec {
  const virtual = `/pg/${schema}/tables/users/rows.jsonl`
  return new PathSpec({
    virtual,
    directory: `/pg/${schema}/tables/users/`,
    resolved: true,
    vfsPath: mountKey(virtual, '/pg'),
  })
}

async function wcLines(path: PathSpec): Promise<[string, number, string]> {
  const cmd = POSTGRES_WC[0]
  if (cmd === undefined) throw new Error('wc not registered')
  const accessor = new PostgresAccessor(
    new StubDriver(),
    resolvePostgresConfig({ dsn: 'postgres://h/db', schemas: ['public'] }),
  )
  const result = await cmd.fn(accessor, [path], [], {
    stdin: null,
    flags: { lines: true },
    filetypeFns: null,
    cwd: '/',
  })
  if (result === null) throw new Error('wc returned nothing')
  const [out, io] = result
  const dec = new TextDecoder()
  const stdout = dec.decode(await materialize(out))
  const stderr = dec.decode(await materialize(io.stderr))
  return [stdout, io.exitCode, stderr]
}

describe('postgres wc -l', () => {
  beforeEach(() => {
    vi.mocked(clientModule.countRows).mockReset()
    vi.mocked(clientModule.listSchemas).mockImplementation((_accessor, allow) =>
      Promise.resolve(['public', 'secret'].filter((s) => allow == null || allow.includes(s))),
    )
    vi.mocked(clientModule.listTables).mockResolvedValue(['users'])
  })

  it('counts a visible table server-side', async () => {
    vi.mocked(clientModule.countRows).mockResolvedValue(42)
    const [stdout, code] = await wcLines(rows('public'))
    expect(stdout).toBe('42 /pg/public/tables/users/rows.jsonl\n')
    expect(code).toBe(0)
  })

  // The count queried the relation by the names in the path, so a table under
  // a schema `schemas` leaves out printed its row count.
  it('refuses a table outside schemas without counting it', async () => {
    vi.mocked(clientModule.countRows).mockRejectedValue(new Error('counted the relation'))
    const [, code, stderr] = await wcLines(rows('secret'))
    expect(code).toBe(1)
    expect(stderr).toContain('No such file or directory')
    expect(clientModule.countRows).not.toHaveBeenCalled()
  })
})
