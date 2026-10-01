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

import { buffer } from 'node:stream/consumers'
import type { Command } from 'commander'
import { makeClient } from './client.ts'
import { emit, exitCodeFromResponse, handleResponse } from './output.ts'
import { loadDaemonSettings } from './settings.ts'

export function registerExecuteCommand(program: Command): void {
  program
    .command('execute')
    .description('Execute a command.')
    .requiredOption('-w, --workspace <id>', 'Workspace id')
    .requiredOption('-c, --command <command>', 'Shell command to execute')
    .option('-s, --session <id>', 'Session id')
    .option('--cwd <path>', 'Working directory for this line (a workspace path)')
    .option('--runtime <name>', "Workspace runtime entry to place this line's captured stages on")
    .option('--bg', 'Background; return job_id immediately')
    .action(
      async (opts: {
        workspace: string
        command: string
        session?: string
        cwd?: string
        runtime?: string
        bg?: boolean
      }) => {
        const body: Record<string, unknown> = { command: opts.command }
        if (opts.session !== undefined) body.sessionId = opts.session
        if (opts.cwd !== undefined) body.cwd = opts.cwd
        if (opts.runtime !== undefined) body.runtime = opts.runtime
        const path =
          `/v1/workspaces/${opts.workspace}/execute` + (opts.bg === true ? '?background=true' : '')
        const c = makeClient(loadDaemonSettings())
        await c.ensureRunning({ allowSpawn: false })
        let result: Response
        if (opts.bg !== true && !process.stdin.isTTY) {
          const form = new FormData()
          form.set(
            'request',
            new Blob([JSON.stringify(body)], { type: 'application/json' }),
            'request.json',
          )
          form.set(
            'stdin',
            new Blob([await buffer(process.stdin)], { type: 'application/octet-stream' }),
            'stdin.bin',
          )
          result = await c.requestMultipart('POST', path, form)
        } else {
          result = await c.request('POST', path, { body: JSON.stringify(body) })
        }
        const response = await handleResponse(result)
        emit(response)
        process.exitCode = exitCodeFromResponse(response)
      },
    )
}
