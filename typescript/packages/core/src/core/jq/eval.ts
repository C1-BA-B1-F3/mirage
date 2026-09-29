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

import * as jqWasm from 'jq-wasm'
import { JqCompileError } from './errors.ts'
import {
  ARGS_VAR,
  INPUTS_VAR,
  NAMED_VAR,
  VALUE_VAR,
  type JqError,
  type JqHalt,
  type JqOptions,
  type JqRun,
  type StreamReads,
} from './types.ts'

// The convenience raw() cache keeps an aborted instance; own its lifecycle here.
let instance: Promise<jqWasm.Jq> | null = null

async function evaluator(): Promise<jqWasm.Jq> {
  instance ??= jqWasm.loadJq().catch((error: unknown) => {
    instance = null
    throw error
  })
  return instance
}

const INPUT_REF = /(?<![\w$.:])input(?![\w:])/
const INPUTS_REF = /(?<![\w$.:])inputs(?![\w:])/
const INPUT_DEF = /(?<![\w$.:])def\s+input\s*[:(]/
const INPUTS_DEF = /(?<![\w$.:])def\s+inputs\s*[:(]/
const ARGS_REF = /\$ARGS(?![\w:])/
const HALT_REF = /(?<![\w$.:])halt(?:_error)?(?![\w:])/
const HALT_ERROR_REF = /(?<![\w$.:])halt_error(?![\w:])/
const TOP_LEVEL_LINE = /(at <top-level>, line )(\d+)/g
const IDENT = /[A-Za-z_][A-Za-z0-9_]*/y
const NAME = /^[A-Za-z_][A-Za-z0-9_]*$/
const TO_STREAM = 'tostream'
const INTERP = '\\('
const OPENERS = '([{'
const CLOSERS = ')]}'

/**
 * Blank out every part of a jq program that cannot be a call.
 *
 * Three things are replaced by spaces: string bodies, `#` comments, and the
 * field names an object shorthand abbreviates (`{a, inputs}` is
 * `{a: .a, inputs: .inputs}`). Interpolations stay code, because
 * `"\(inputs)"` really does call the builtin, so everything between `\(`
 * and its closing paren survives, nested strings included.
 */
function codeOnly(expr: string): string {
  const out: string[] = []
  // Open brackets, innermost last, with an interpolation recorded as one
  // too; empty means the scan is at the top level of the program.
  const stack: string[] = []
  let inString = false
  let prev = ''
  let i = 0
  while (i < expr.length) {
    const ch = expr.charAt(i)
    if (inString) {
      if (ch === '\\' && i + 1 < expr.length) {
        if (expr.charAt(i + 1) === '(') {
          inString = false
          stack.push(INTERP)
        }
        out.push('  ')
        i += 2
        continue
      }
      inString = ch !== '"'
      out.push(' ')
      i += 1
      continue
    }
    if (ch === '"') {
      inString = true
      out.push(' ')
      i += 1
      continue
    }
    if (ch === '#') {
      while (i < expr.length && expr.charAt(i) !== '\n') {
        out.push(' ')
        i += 1
      }
      continue
    }
    IDENT.lastIndex = i
    const word = IDENT.exec(expr)
    if (word !== null) {
      const text = word[0]
      const key = stack[stack.length - 1] === '{' && (prev === '{' || prev === ',')
      out.push(key ? ' '.repeat(text.length) : text)
      prev = text.charAt(text.length - 1)
      i += text.length
      continue
    }
    if (OPENERS.includes(ch)) {
      stack.push(ch)
    } else if (ch === ')' && stack[stack.length - 1] === INTERP) {
      stack.pop()
      inString = true
      out.push(' ')
      prev = ''
      i += 1
      continue
    } else if (CLOSERS.includes(ch) && stack.length > 0 && stack[stack.length - 1] !== INTERP) {
      stack.pop()
    }
    out.push(ch)
    if (ch.trim() !== '') prev = ch
    i += 1
  }
  return out.join('')
}

/**
 * Report which of the builtins that read the input stream a program calls.
 *
 * Binding the unread documents is what makes `input` and `inputs` work,
 * and it also changes how many documents a run consumes, so only the
 * builtins may answer here: the words also spell a field (`.inputs`,
 * `{inputs}`), a variable (`$inputs`), an object key (`{inputs: 1}`), a
 * module member (`m::inputs`), a function the program defines for itself
 * (`def input: ...`), and anything at all inside a string or a comment,
 * none of which read the stream.
 */
export function streamReads(expr: string): StreamReads {
  const code = codeOnly(expr)
  return {
    input: INPUT_REF.test(code) && !INPUT_DEF.test(code),
    inputs: INPUTS_REF.test(code) && !INPUTS_DEF.test(code),
  }
}

/** Report whether a jq program reads the `$ARGS` variable. */
export function referencesArgs(expr: string): boolean {
  return ARGS_REF.test(codeOnly(expr))
}

/** Report whether a jq program can call `halt` or `halt_error`. */
export function halts(expr: string): boolean {
  return HALT_REF.test(codeOnly(expr))
}

/** The value `$ARGS` resolves to for a run. */
export function argsObject(opts: JqOptions): Record<string, unknown> {
  return { positional: [...opts.positionalArgs], named: { ...opts.namedArgs } }
}

/**
 * The `[path, leaf]` events `--stream` reads a document as.
 *
 * jq's own `tostream` emits exactly the events `--stream` produces for a
 * complete document; the two differ only for input too truncated to
 * parse, which never reaches here because mirage reads whole values.
 */
export function streamEvents(doc: unknown): Promise<unknown[]> {
  return jqEval(doc, TO_STREAM)
}

/**
 * The definitions `input` and `inputs` read the unread documents through.
 *
 * `input` takes the first of them and, once none is left, fails the way jq
 * 1.7 and 1.8 both do, with the error `break`. `inputs` yields the ones
 * after it, or all of them when the program never calls `input`: the
 * stream as the two builtins leave it for each other when `input` runs
 * once, ahead of `inputs`.
 */
function streamDefs(expr: string): string {
  const docs = `$${INPUTS_VAR}`
  const rest = streamReads(expr).input ? `${docs}[1:]` : docs
  return (
    `def input: if (${docs} | length) > 0 then ${docs}[0] else error("break") end; ` +
    `def inputs: ${rest}[];`
  )
}

/**
 * A token drawn from the platform's random source, which, unlike
 * `crypto.randomUUID`, every browser context has.
 */
function randomToken(): string {
  const bytes = new Uint8Array(16)
  crypto.getRandomValues(bytes)
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')
}

// The keys the prelude hands a run's stop back under: the error no `try`
// caught, the halt `halt` or `halt_error` asked for, and the end of a run
// that did not halt. Each carries a token drawn once per process, so no
// output of a program can pass for one.
const TOKEN = randomToken()
const ERROR_KEY = `__mirage_jq_error_${TOKEN}`
const HALT_KEY = `__mirage_jq_halt_${TOKEN}`
const DONE_KEY = `__mirage_jq_done_${TOKEN}`

// The error no `try` inside the program caught: whether it was a string,
// and its text as jq prints it.
const ERROR_MARK =
  `{"${ERROR_KEY}": [(type == "string"), ` + '(if type == "string" then . else tojson end)]}'
const CATCH = ` catch ${ERROR_MARK}`
const DONE = `, {"${DONE_KEY}": true}`

// A run keeps jq's own `halt` and `halt_error`, which no `try` catches and
// which end the program wherever they are called; one that halted is the run
// that never reaches the sentinel after the program. jq-wasm reports a halt
// only as the end of the outputs, an exit code and the stderr jq writes, so
// its message and code come from running the program again with the two
// redefined, first to raise them as an error the top-level `catch` hands back
// (which leaves any collector, `[halt_error]` or `map`), and when a `try` of
// the program's own caught that, to print them just before the real halt.
// Either answer counts only when the run printed as many outputs up to it as
// the first run did: the two are one run up to the first halt, so a later
// halt shows as more outputs before it, where the values themselves can
// differ (`now`). A `try` that swallows one halt unseen before the program
// reaches another still gets past that.
const HALT_MARK =
  `{"${HALT_KEY}": [$code, (if . == null then null ` +
  'elif type == "string" then . else tojson end), (type == "string")]}'
const BUILTINS =
  'def __mirage_jq_halt: halt; def __mirage_jq_halt_error($code): halt_error($code); '
const RAISE =
  BUILTINS +
  `def halt: error({"${HALT_KEY}": [null, null, false]}); ` +
  'def halt_error($code): if ($code | type) == "number" then ' +
  `error(${HALT_MARK}) else __mirage_jq_halt_error($code) end; ` +
  'def halt_error: halt_error(5); '
const RAISED = ` catch (if type == "object" and has("${HALT_KEY}") then . else ${ERROR_MARK} end)`
const PRINT =
  BUILTINS +
  `def halt: {"${HALT_KEY}": [null, null, false]}, __mirage_jq_halt; ` +
  'def halt_error($code): if ($code | type) == "number" then ' +
  `${HALT_MARK}, __mirage_jq_halt_error($code) else __mirage_jq_halt_error($code) end; ` +
  'def halt_error: halt_error(5); '

// How jq-wasm's jq reports an error no `try` caught, which only a program
// the prelude could not wrap leaves to it.
const REPORTED = /jq: error \(at [^)\n]*\)( \(not a string\))?: /g

// jq's exit status when it refuses the program itself, and the line its
// refusal ends on: a halt can exit 3 too.
const ERROR_COMPILE = 3
const COMPILE_REFUSAL = /jq: \d+ compile errors?\n?$/

/** One run as jq-wasm is handed it: the prelude steps and its stdin. */
interface Bound {
  readonly steps: readonly string[]
  readonly stdin: string
  /** The plain document, for a program that goes bare. */
  readonly plain: string
}

/**
 * The bindings one run carries.
 *
 * Every value a run binds travels on stdin, inside one wrapper document the
 * prelude unpacks, and never on the command line: jq-wasm copies each argv
 * string onto its fixed-size WebAssembly stack, which one argument near
 * 1 MiB runs off the end of (a trap, or a silent overwrite of jq's own
 * data), while stdin is read from the heap. A run that binds nothing goes
 * on the plain document.
 */
function bound(
  obj: unknown,
  expr: string,
  namedArgs: Readonly<Record<string, unknown>>,
  inputs: readonly unknown[] | null,
  argsValue: Readonly<Record<string, unknown>> | null,
): Bound {
  const plain = JSON.stringify(obj)
  // A name that is not an identifier can never be spelled as a variable,
  // so nothing needs it bound; $ARGS.named still carries it.
  const names = Object.keys(namedArgs).filter((name) => NAME.test(name))
  if (names.length === 0 && inputs === null && argsValue === null) {
    return { steps: [], stdin: plain, plain }
  }
  const steps = [`. as [$${VALUE_VAR}, $${NAMED_VAR}, $${INPUTS_VAR}, $${ARGS_VAR}] |`]
  for (const name of names) steps.push(`$${NAMED_VAR}[${JSON.stringify(name)}] as $${name} |`)
  if (inputs !== null) steps.push(streamDefs(expr))
  // jq defines $ARGS itself, from a command line that no longer carries
  // the bindings, so the only way to serve mirage's own is to rebind it.
  if (argsValue !== null) steps.push(`$${ARGS_VAR} as $ARGS |`)
  steps.push(`$${VALUE_VAR} |`)
  return { steps, stdin: JSON.stringify([obj, namedArgs, inputs ?? [], argsValue]), plain }
}

/** A compile error as the program's own lines number it. */
function unshifted(message: string, shift: number): string {
  if (shift === 0) return message
  return message.replace(
    TOP_LEVEL_LINE,
    (_match: string, head: string, line: string) => `${head}${String(Number(line) - shift)}`,
  )
}

/** Whether jq-wasm's jq refused the program rather than running it. */
function refused(result: jqWasm.JqResult): boolean {
  return (
    result.exitCode === ERROR_COMPILE && result.stdout === '' && COMPILE_REFUSAL.test(result.stderr)
  )
}

/**
 * Whether every bracket in a program's code closes the one opened last,
 * which is what keeps the program whole inside the prelude's own
 * parentheses: code that closes one early could otherwise pair with them
 * into a program jq itself would refuse.
 */
function balanced(code: string): boolean {
  const stack: string[] = []
  for (const ch of code) {
    if (OPENERS.includes(ch)) stack.push(ch)
    else if (CLOSERS.includes(ch) && OPENERS[CLOSERS.indexOf(ch)] !== stack.pop()) return false
  }
  return stack.length === 0
}

/** jq-wasm's run of a program over a stdin, its outputs compact. */
async function raw(stdin: string, program: string): Promise<jqWasm.JqResult> {
  const jq = await evaluator()
  try {
    return jq.raw(stdin, program, ['-c'])
  } catch (error) {
    if (!(error instanceof WebAssembly.RuntimeError)) throw error
    instance = null
    const bytes = new TextEncoder().encode(stdin).byteLength
    // This is the pinned build's reproduced allocation-abort signature.
    const detail =
      error.message === 'Aborted(). Build with -sASSERTIONS for more info.'
        ? 'This jq-wasm build has a 256 MiB heap limit; parsed JSON and query ' +
          'allocations can exceed the input size. Reduce the input or use a native jq runtime. '
        : `WebAssembly trap: ${error.message}. `
    throw new Error(
      `WASM evaluation failed for ${String(bytes)} bytes of JSON input. ` +
        detail +
        'The evaluator has been reset for the next call.',
      { cause: error },
    )
  }
}

/** The stop the prelude hands back as a run's output, when this output is one. */
function stopOf(value: unknown): JqError | JqHalt | null {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return null
  const keys = Object.keys(value)
  if (keys.length !== 1) return null
  const record = value as Record<string, unknown>
  const error = record[ERROR_KEY]
  if (Array.isArray(error) && error.length === 2) {
    return { kind: 'error', text: String(error[1]), string: error[0] === true }
  }
  const halt = record[HALT_KEY]
  if (Array.isArray(halt) && halt.length === 3) {
    const [code, message, string] = halt as unknown[]
    return {
      kind: 'halt',
      message: typeof message === 'string' ? message : null,
      string: string === true,
      code: typeof code === 'number' ? code : null,
    }
  }
  return null
}

/**
 * A run's outputs, up to the stop the prelude hands back, and whether the run
 * ended by itself rather than stopping at a halt: it reached the sentinel,
 * handed back a stop, or failed. A run with no sentinel ends when jq does;
 * only a program the prelude could not wrap exits with an error then, which
 * jq has reported on stderr.
 */
function collected(result: jqWasm.JqResult, sentinel: boolean): [JqRun, boolean] {
  const outputs: unknown[] = []
  for (const line of result.stdout.split('\n')) {
    if (line === '') continue
    const value = JSON.parse(line) as unknown
    if (value !== null && typeof value === 'object' && DONE_KEY in value) {
      return [{ outputs, stop: null }, true]
    }
    const stop = stopOf(value)
    if (stop !== null) return [{ outputs, stop }, true]
    outputs.push(value)
  }
  if (sentinel) return [{ outputs, stop: null }, false]
  if (result.exitCode === 0) return [{ outputs, stop: null }, true]
  let text = result.stderr.replace(/\n$/, '') || `jq exited with code ${String(result.exitCode)}`
  let string = true
  for (const match of result.stderr.matchAll(REPORTED)) {
    text = result.stderr.slice(match.index + match[0].length).replace(/\n$/, '')
    string = match[1] === undefined
  }
  return [{ outputs, stop: { kind: 'error', text, string } }, true]
}

/**
 * The program inside the prelude (see jqRun), or null when its code cannot
 * sit whole inside the prelude's parentheses. `stops` are the definitions
 * `halt` and `halt_error` run as, and `tail` what follows the program: its
 * `catch`, and the sentinel of a run that keeps the real halts.
 */
function wrapped(bindings: Bound, expr: string, stops: string, tail: string): string | null {
  const code = codeOnly(expr)
  if (code.trim() === '' || !balanced(code)) return null
  const prelude = stops + bindings.steps.map((step) => `${step} `).join('')
  return `${prelude}(try (${expr}\n)${tail}`
}

/**
 * One run of the program as jq-wasm runs it, and whether it carries the
 * sentinel: inside the prelude, or, when its code cannot sit whole inside
 * the prelude's parentheses or the prelude's text is refused, as typed behind
 * the definitions that print a halt just before it. As typed, the prelude
 * costs one line, so the line a compile error reports is moved back by it; a
 * program with no code for jq to run at all goes bare, which keeps jq's own
 * refusal of an empty program. Throws JqCompileError for libjq's refusal of
 * the program, its compile errors numbered by the program's own lines.
 */
async function ran(
  bindings: Bound,
  expr: string,
  empty: boolean,
): Promise<[jqWasm.JqResult, boolean]> {
  const stdin = (text: string): string => (empty ? '' : text)
  const program = wrapped(bindings, expr, '', `${CATCH})${DONE}`)
  if (program !== null) {
    const result = await raw(stdin(bindings.stdin), program)
    if (!refused(result)) return [result, true]
  }
  const shift = codeOnly(expr).trim() === '' ? 0 : 1
  const result =
    shift === 0
      ? await raw(stdin(bindings.plain), expr)
      : await raw(stdin(bindings.stdin), `${PRINT}${bindings.steps.join(' ')}\n${expr}`)
  if (refused(result)) {
    throw new JqCompileError(unshifted(result.stderr, shift).replace(/\n$/, ''))
  }
  return [result, false]
}

/**
 * The message and code of the halt a run stopped at, from running the
 * program again with the halts redefined (see RAISE and PRINT).
 */
async function haltOf(bindings: Bound, expr: string, printed: number): Promise<JqHalt> {
  for (const [stops, tail] of [
    [RAISE, `${RAISED})`],
    [PRINT, `${CATCH})`],
  ] as const) {
    const program = wrapped(bindings, expr, stops, tail)
    if (program === null) continue
    const [again] = collected(await raw(bindings.stdin, program), false)
    if (again.stop?.kind === 'halt' && again.outputs.length === printed) return again.stop
  }
  // A halt caught by the program's own `try` inside a collector keeps its
  // message from both, so it reads as halt_error's default.
  const code = HALT_ERROR_REF.test(codeOnly(expr)) ? 5 : null
  return { kind: 'halt', message: null, string: false, code }
}

/**
 * Run a jq program on one value, the way jq's main loop runs it on one
 * document.
 *
 * A jq program is a stream transformer: it emits zero, one or many values,
 * and jq prints each on its own line. That arity is preserved here rather
 * than collapsed, so two outputs are never confused with one output that
 * happens to be an array. `.a, .b` yields two values; `[.a, .b]` yields
 * one.
 *
 * An error that no `try` catches ends the run, and jq still prints what
 * came before it; `halt` and `halt_error` end the whole invocation. The
 * program runs inside a prelude that catches the error and hands it back as
 * the run's last output, which is how the run knows it whole where jq-wasm
 * would print it, with a sentinel after the program that only a run that did
 * not halt reaches (see haltOf for what a halt said). The whole prelude sits
 * on the program's first line, so the program's lines keep their numbers.
 *
 * `namedArgs` are the $name bindings from --arg / --argjson / --rawfile /
 * --slurpfile. `inputs` are the documents still unread at this point in
 * the stream, which `input` and `inputs` read (see streamDefs): this
 * evaluator is handed one value at a time and owns no input stream, so
 * both builtins are bound as definitions over those documents instead. A
 * user program that defines its own shadows the binding, as it would
 * shadow the builtin.
 */
export async function jqRun(
  obj: unknown,
  expr: string,
  namedArgs: Readonly<Record<string, unknown>> = {},
  inputs: readonly unknown[] | null = null,
  argsValue: Readonly<Record<string, unknown>> | null = null,
): Promise<JqRun> {
  const bindings = bound(obj, expr, namedArgs, inputs, argsValue)
  const [run, ended] = collected(...(await ran(bindings, expr, false)))
  if (ended) return run
  return { outputs: run.outputs, stop: await haltOf(bindings, expr, run.outputs.length) }
}

/**
 * Compile a program the way a run would, without running it: on an empty
 * stdin, which jq reads no document from. jq compiles its program before
 * it reads any input, so it refuses a bad one even when there is no
 * document to run it on. Throws JqCompileError for the refusal.
 */
export async function jqCheck(
  expr: string,
  namedArgs: Readonly<Record<string, unknown>> = {},
  inputs: readonly unknown[] | null = null,
  argsValue: Readonly<Record<string, unknown>> | null = null,
): Promise<void> {
  await ran(bound(null, expr, namedArgs, inputs, argsValue), expr, true)
}

/**
 * Every output of a jq program on one value (see jqRun), for a caller that
 * treats an error as a failure of its own: it throws with the error's
 * text, and with libjq's refusal of the program.
 */
export async function jqEval(
  obj: unknown,
  expr: string,
  namedArgs: Readonly<Record<string, unknown>> = {},
  inputs: readonly unknown[] | null = null,
  argsValue: Readonly<Record<string, unknown>> | null = null,
): Promise<unknown[]> {
  const run = await jqRun(obj, expr, namedArgs, inputs, argsValue)
  if (run.stop?.kind === 'error') throw new Error(run.stop.text)
  return run.outputs
}
