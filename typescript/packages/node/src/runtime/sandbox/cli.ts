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

import { spawn } from 'node:child_process'

export interface CliResult {
  stdout: Uint8Array
  stderr: Uint8Array
  code: number
}

/**
 * One sandbox CLI invocation: its output and its exit status. An aborted
 * call kills the child, so a line abandoned to a timeout does not leave the
 * CLI running behind it; a missing CLI rejects with `hint`. EPIPE means the
 * command exited without draining its stdin (`head`-like); python's
 * communicate() suppresses the matching BrokenPipeError, so it is not an
 * error here either. Mirrors Python's `run_cli`.
 */
export function runCli(
  executable: string,
  hint: string,
  args: string[],
  stdin: Uint8Array | null,
  signal?: AbortSignal,
): Promise<CliResult> {
  return new Promise((resolve, reject) => {
    const child = spawn(executable, args, {
      stdio: ['pipe', 'pipe', 'pipe'],
      signal,
      killSignal: 'SIGKILL',
    })
    const out: Buffer[] = []
    const err: Buffer[] = []
    child.stdout.on('data', (chunk: Buffer) => out.push(chunk))
    child.stderr.on('data', (chunk: Buffer) => err.push(chunk))
    child.on('error', (error: NodeJS.ErrnoException) => {
      reject(error.code === 'ENOENT' ? new Error(hint) : error)
    })
    child.on('close', (code) => {
      resolve({
        stdout: new Uint8Array(Buffer.concat(out)),
        stderr: new Uint8Array(Buffer.concat(err)),
        code: code ?? 1,
      })
    })
    child.stdin.on('error', (error: NodeJS.ErrnoException) => {
      if (error.code !== 'EPIPE') reject(error)
    })
    if (stdin !== null) child.stdin.write(stdin)
    child.stdin.end()
  })
}
