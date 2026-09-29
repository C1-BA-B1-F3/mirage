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

export const DEFAULT_INDENT = 2

// The variables a run's prelude binds. Spelled so a user program can
// never collide with them by accident.

// The unread documents `input` and `inputs` read.
export const INPUTS_VAR = '__mirage_jq_inputs'

// The value the `$ARGS` prelude rebinds.
export const ARGS_VAR = '__mirage_jq_args'

// The document the program runs on, once the prelude has unpacked it.
export const VALUE_VAR = '__mirage_jq_value'

// The --arg / --argjson / --rawfile / --slurpfile bindings, by name.
export const NAMED_VAR = '__mirage_jq_named'

// The keys a run's prelude hands its stop back under: the error no `try`
// caught, and the halt `halt` or `halt_error` asked for. Spelled so a
// user program never prints one by accident.
export const ERROR_KEY = '__mirage_jq_error'
export const HALT_KEY = '__mirage_jq_halt'

// What jq names standard input when it reports where it stands, and what
// it reports before it has read any input at all.
export const STDIN_NAME = '<stdin>'
export const UNKNOWN_POSITION = '<unknown>'

/**
 * An error no `try` caught, which ends one run: jq reports it and goes on
 * with the next document.
 */
export interface JqError {
  readonly kind: 'error'
  /** The message as jq prints it: a string as it is, anything else in
   * jq's own compact dump. */
  readonly text: string
  /** Whether the message was a string, which jq's report says when it
   * was not. */
  readonly string: boolean
}

/** `halt` or `halt_error`, which end the whole invocation. */
export interface JqHalt {
  readonly kind: 'halt'
  /** What jq writes to stderr for it, as it is. */
  readonly text: string
  /** The exit code `halt_error` named, or null for `halt`. */
  readonly code: number | null
}

/** What one run of a program printed, and what ended it early. */
export interface JqRun {
  /** Every value it printed, in order. */
  readonly outputs: unknown[]
  /** The error or the halt that ended it, or null when it ran to its end. */
  readonly stop: JqError | JqHalt | null
}

/** Which of the builtins that read the input stream a program calls. */
export interface StreamReads {
  /** `input`, which takes the next unread document. */
  readonly input: boolean
  /** `inputs`, which yields every unread document. */
  readonly inputs: boolean
}

// The record separator an application/json-seq stream puts before every
// value (RFC 7464).
export const RS = '\u001e'

/**
 * One jq invocation's resolved options.
 *
 * The command line's implications are already applied by the caller
 * (`-j` and `--raw-output0` imply `-r`, `--tab` and `--indent` resolve
 * into one indent width), so every consumer reads plain fields. Mirrors
 * Python's JqOptions.
 */
export interface JqOptions {
  /** -n, run the program once against null and never read the inputs as
   * the program's input. */
  readonly nullInput: boolean
  /** -R, each input line is a string instead of a JSON document. */
  readonly rawInput: boolean
  /** -s, collapse the whole input stream into one value (an array of
   * documents, or one string under -R). */
  readonly slurp: boolean
  /** --stream, replace each input document with its [path, leaf] events,
   * the same ones `tostream` emits. */
  readonly stream: boolean
  /** --seq, read and write RFC 7464 JSON text sequences (every value
   * preceded by RS). */
  readonly seq: boolean
  /** -r, print a string output unquoted. */
  readonly rawOutput: boolean
  /** -j, write no separator after an output. */
  readonly joinOutput: boolean
  /** --raw-output0, write a NUL after an output. */
  readonly nulOutput: boolean
  /** -c, one line of JSON per output. */
  readonly compact: boolean
  /** -a, escape every non-ASCII character. jq prints strings quoted
   * under -a even with -r. */
  readonly asciiOutput: boolean
  /** -S, sort object keys. */
  readonly sortKeys: boolean
  /** Indent with one tab per level. */
  readonly tab: boolean
  /** Spaces per indent level when not compact. */
  readonly indent: number
  /** -e, derive the exit code from the last output value. */
  readonly exitStatus: boolean
  /** --arg / --argjson / --rawfile / --slurpfile bindings, as the values
   * $name resolves to. */
  readonly namedArgs: Readonly<Record<string, unknown>>
  /** --args / --jsonargs values, in order, as $ARGS.positional reports
   * them. */
  readonly positionalArgs: readonly unknown[]
}

const DEFAULT_JQ_OPTIONS: JqOptions = Object.freeze({
  nullInput: false,
  rawInput: false,
  slurp: false,
  stream: false,
  seq: false,
  rawOutput: false,
  joinOutput: false,
  nulOutput: false,
  compact: false,
  asciiOutput: false,
  sortKeys: false,
  tab: false,
  indent: DEFAULT_INDENT,
  exitStatus: false,
  namedArgs: Object.freeze({}),
  positionalArgs: Object.freeze([]),
})

/** A JqOptions built from the fields that differ from the defaults. */
export function jqOptions(overrides: Partial<JqOptions> = {}): JqOptions {
  return Object.freeze({ ...DEFAULT_JQ_OPTIONS, ...overrides })
}
