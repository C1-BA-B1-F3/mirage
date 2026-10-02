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

import type { ByteSource } from '../io/types.ts'
import type { ArithWrite } from './types.ts'
// ========= Copyright 2026 @ Strukto.AI All Rights Reserved. =========

// A bash arithmetic syntax or evaluation error. Mirrors Python's
// mirage.shell.errors.ArithError.
/**
 * A bash arithmetic syntax or evaluation error. `writes` carries the
 * assignments the expression made before it failed: bash binds each at
 * once, so `x=5, 1/0` leaves `x` at 5 and `RANDOM=42, RANDOM + 1/0`
 * leaves the generator seeded and drawn from. The evaluator fills it as
 * it throws; a caller lands them the way it lands a successful result's,
 * then reports the error.
 */
export class ArithError extends Error {
  writes: ArithWrite[] = []
}

// An arithmetic assignment to a readonly shell variable. Mirrors
// Python's mirage.shell.errors.ReadonlyError.
export class ReadonlyError extends Error {
  readonly varName: string

  constructor(name: string) {
    super(`${name}: readonly variable`)
    this.name = 'ReadonlyError'
    this.varName = name
  }
}

// A fatal shell exit request unwinding the current execution. Raised by
// the `exit` builtin and by fatal expansion errors (`${var:?msg}`), which
// bash treats as an implicit `exit 1` in a non-interactive shell.
// Contained at subshell, pipeline-segment, and background-job boundaries;
// the top-level program loop stops the remaining statements. Mirrors
// Python's mirage.shell.errors.ExitSignal.
export class ExitSignal extends Error {
  readonly exitCode: number
  stderr: Uint8Array
  stdout: Uint8Array | null
  // Status a containing boundary reports instead of exitCode. GNU bash
  // exits 127 on a fatal expansion error but a subshell wrapping one
  // returns 1; `exit N` uses N in both positions (the default).
  readonly containedCode: number

  constructor(
    exitCode = 0,
    stderr: Uint8Array = new Uint8Array(),
    stdout: Uint8Array | null = null,
    containedCode: number | null = null,
  ) {
    super('exit')
    this.name = 'ExitSignal'
    this.exitCode = exitCode
    this.stderr = stderr
    this.stdout = stdout
    this.containedCode = containedCode ?? exitCode
  }
}

/**
 * `set -u` reading a name that is not set: `$x`, `${a[i]}`, or a variable
 * an arithmetic expression reads. GNU bash dies on it the way it dies on
 * `${x:?}`: status 127 at top level, 1 from a containing subshell or
 * pipeline segment. Mirrors Python's mirage.shell.errors.UnboundVariable.
 */
export class UnboundVariable extends ExitSignal {
  constructor(name: string) {
    super(127, new TextEncoder().encode(`bash: ${name}: unbound variable\n`), null, 1)
    this.name = 'UnboundVariable'
  }
}

/**
 * A `${...}` bash cannot read, found as its word expands. bash names the text
 * of the expansion it was running: the whole word, a double-quoted part's
 * inside, an operator's word, an arithmetic expression, a heredoc's body.
 * Each level the error leaves renames it (`within`) until one of those fixes
 * the name. Fatal with status 1, as `$((1/0))` is, and contained the same
 * way. Mirrors Python's mirage.shell.errors.BadSubstitution.
 */
export class BadSubstitution extends ExitSignal {
  private fixed = false

  constructor(text: string) {
    super(1, new Uint8Array(), null, 1)
    this.name = 'BadSubstitution'
    this.within(text)
  }

  /** Name the word being expanded, unless a boundary already has. */
  within(word: string, fixed = false): this {
    if (!this.fixed) {
      this.stderr = new TextEncoder().encode(`bash: ${word}: bad substitution\n`)
      this.fixed = fixed
    }
    return this
  }
}

/**
 * Await an expansion of `word`, which a bad substitution names: a
 * double-quoted part's inside, an operator's word, an arithmetic expression.
 * Mirrors Python's mirage.shell.errors.named.
 */
export async function named<T>(word: string, pending: Promise<T>): Promise<T> {
  try {
    return await pending
  } catch (err) {
    if (err instanceof BadSubstitution) throw err.within(word, true)
    throw err
  }
}

/**
 * `return` unwinding to the function or sourced file it ends; `stdout` is the
 * output the constructs it left had produced before it.
 */
export class ReturnSignal extends Error {
  readonly exitCode: number
  readonly stderr: Uint8Array
  readonly stdout: ByteSource | null
  constructor(
    exitCode: number,
    stderr: Uint8Array = new Uint8Array(),
    stdout: ByteSource | null = null,
  ) {
    super('return')
    this.name = 'ReturnSignal'
    this.exitCode = exitCode
    this.stderr = stderr
    this.stdout = stdout
  }
}

export class PipeClosed extends Error {}
