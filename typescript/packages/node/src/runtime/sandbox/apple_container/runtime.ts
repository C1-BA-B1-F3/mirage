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
import { PROCESS_EXECUTOR, type ProcessExecutor } from '@struktoai/mirage-core/runtime/mixin'
import { RemoteSandbox } from '@struktoai/mirage-core/runtime/sandbox/base'
import { registerRuntime } from '@struktoai/mirage-core/runtime/table'
import type {
  ProcessExecution,
  RunResult,
  RuntimeOptions,
} from '@struktoai/mirage-core/runtime/types'
import { APPLE_CONTAINER_CONFIG_KEYS, type AppleContainerConfig } from './config.ts'
import { APPLE_CONTAINER_CLI_HINT, PRELUDE, RUNNING_STATE, notRunningHint } from './constants.ts'

interface ContainerResult {
  stdout: Uint8Array
  stderr: Uint8Array
  code: number
}

/**
 * A container under Apple's `container` tool as a whole-line runtime.
 *
 * You start the container yourself; mirage only connects to it and
 * execs lines. The `container` CLI is the transport, so there is no
 * SDK dependency and no XPC wiring; each line is one `container exec`
 * with the merged environment, the session cwd, real stdin, and
 * separated stderr.
 *
 * Each container is its own lightweight VM with its own Linux kernel,
 * so, as in a smolvm guest, the line sees nothing of the host's
 * filesystem except what the container was given at start
 * (`--volume`). Serve the workspace inside it at the host's mount
 * prefixes, the same contract every provider in this family carries.
 * The image needs a POSIX sh, which every argv runs under (PRELUDE).
 */
export class AppleContainerRuntime
  extends RemoteSandbox<AppleContainerConfig>
  implements ProcessExecutor
{
  readonly [PROCESS_EXECUTOR] = true as const
  readonly name = 'apple_container'

  constructor(options: RuntimeOptions<AppleContainerConfig> | Record<string, unknown> = {}) {
    super(options, APPLE_CONTAINER_CONFIG_KEYS)
    if (!this.config.container) {
      throw new Error('apple_container config needs container: the id of a running container')
    }
  }

  // One container CLI invocation; the seam tests override.
  protected container(
    args: string[],
    stdin: Uint8Array | null = null,
    signal?: AbortSignal,
  ): Promise<ContainerResult> {
    return new Promise((resolve, reject) => {
      const child = spawn('container', args, {
        stdio: ['pipe', 'pipe', 'pipe'],
        signal,
        killSignal: 'SIGKILL',
      })
      const out: Buffer[] = []
      const err: Buffer[] = []
      child.stdout.on('data', (chunk: Buffer) => out.push(chunk))
      child.stderr.on('data', (chunk: Buffer) => err.push(chunk))
      child.on('error', (error: NodeJS.ErrnoException) => {
        reject(error.code === 'ENOENT' ? new Error(APPLE_CONTAINER_CLI_HINT) : error)
      })
      child.on('close', (code) => {
        resolve({
          stdout: new Uint8Array(Buffer.concat(out)),
          stderr: new Uint8Array(Buffer.concat(err)),
          code: code ?? 1,
        })
      })
      // EPIPE means the guest command exited without draining its
      // stdin (`head`-like); python's communicate() suppresses the
      // matching BrokenPipeError, so it is not an error here either.
      child.stdin.on('error', (error: NodeJS.ErrnoException) => {
        if (error.code !== 'EPIPE') reject(error)
      })
      if (stdin !== null) child.stdin.write(stdin)
      child.stdin.end()
    })
  }

  /**
   * Probe the container, refusing any state that cannot take a line.
   *
   * `container exec` refuses a container that is not running as well;
   * probing once up front names the state and how to recover.
   */
  async connect(): Promise<void> {
    const result = await this.container(['inspect', this.config.container])
    if (result.code !== 0) {
      throw new Error(`container inspect failed: ${decode(result.stderr).trim()}`)
    }
    let state: unknown
    try {
      state = inspectedState(JSON.parse(decode(result.stdout)))
    } catch (error) {
      throw new Error(`container inspect returned unreadable json: ${String(error)}`)
    }
    if (state !== RUNNING_STATE) {
      throw new Error(notRunningHint(this.config.container, String(state)))
    }
  }

  async execLine(
    line: string,
    stdin: Uint8Array | null,
    env: Record<string, string>,
    cwd: string,
    signal?: AbortSignal,
  ): Promise<RunResult> {
    return this.execArgv(['sh', '-c', line], stdin, env, cwd, signal)
  }

  async runProcess(request: ProcessExecution): Promise<RunResult> {
    if (request.argv.length === 0) throw new Error('process argv must not be empty')
    await this.ensureConnected(request.signal)
    return this.execArgv(
      request.argv,
      request.stdin,
      { ...this.config.env, ...request.env },
      request.cwd.virtual,
      request.signal,
    )
  }

  private async execArgv(
    argv: readonly string[],
    stdin: Uint8Array | null,
    env: Record<string, string>,
    cwd: string,
    signal?: AbortSignal,
  ): Promise<RunResult> {
    const args = ['exec', '-i', '-w', '/']
    for (const [key, value] of Object.entries(env)) args.push('-e', `${key}=${value}`)
    args.push(this.config.container, 'sh', '-c', PRELUDE, 'sh', cwd, ...argv)
    const result = await this.container(args, stdin, signal)
    return { stdout: result.stdout, stderr: result.stderr, exitCode: result.code }
  }
}

/** The first entry's `status.state`, throwing on any other shape. */
function inspectedState(payload: unknown): unknown {
  const entry: unknown = Array.isArray(payload) ? payload[0] : undefined
  const status: unknown =
    typeof entry === 'object' && entry !== null ? (entry as { status?: unknown }).status : undefined
  if (typeof status !== 'object' || status === null || !('state' in status)) {
    throw new Error('expected [{ status: { state } }]')
  }
  return status.state
}

const DECODER = new TextDecoder()

function decode(bytes: Uint8Array): string {
  return DECODER.decode(bytes)
}

registerRuntime('apple_container', AppleContainerRuntime)
