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

// Command-line usage error (GNU semantics: stderr message + exit code).
// The message is the full stderr text (may span lines for the
// `Try '--help'` hint). Most tools exit 2 for option errors but 1 for
// operand errors, and the raiser knows which (`usageExitCode` for the
// per-command table). Mirrors Python's mirage.commands.errors.UsageError.
export class UsageError extends Error {
  readonly exitCode: number

  constructor(message: string, exitCode = 2) {
    super(message)
    this.exitCode = exitCode
  }
}

// Invalid numeric argument to a find predicate (GNU find: exit 1).
// Mirrors Python's mirage.commands.errors.FindParseError.
export class FindParseError extends Error {}

// A command or op overran its timeout budget (exit 124).
// Mirrors Python's mirage.commands.errors.CommandTimeoutError.
export class CommandTimeoutError extends Error {
  readonly command: string
  readonly seconds: number
  constructor(command: string, seconds: number) {
    super(`${command}: timed out after ${String(seconds)}s`)
    this.name = 'CommandTimeoutError'
    this.command = command
    this.seconds = seconds
  }
}

// What a listing reports against the one entry whose stat failed, and walks
// past: GNU's ls and find carry on from any failed stat below an operand,
// whatever the errno, so a dropped connection or a 5xx on a mount whose stat
// is a request costs that entry alone. Only what ends the whole command
// still ends it: the line's abort and its timeout. Mirrors Python's
// is_entry_error.
export function isEntryError(err: unknown): boolean {
  if (err instanceof CommandTimeoutError) return false
  return (err as { name?: unknown } | null)?.name !== 'AbortError'
}

/**
 * A hard cap refused output the producer had already made.
 *
 * The cap is applied to a result that exists: at an op door the
 * backend has already moved those bytes, and the door reports that
 * through the caller's `OpReport` before the cap runs, so this error
 * carries no accounting of its own.
 * Mirrors Python's mirage.commands.errors.LimitExceededError.
 */
export class LimitExceededError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'LimitExceededError'
  }
}
