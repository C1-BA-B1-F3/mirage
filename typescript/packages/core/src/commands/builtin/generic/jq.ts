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

import { specOf } from '../../spec/builtins.ts'
import { FlagView } from '../../spec/flag_view.ts'
import {
  DEFAULT_INDENT,
  InputReader,
  JqCompileError,
  JqParseError,
  NO_VALUE,
  STDIN_NAME,
  argsObject,
  decodeUtf8,
  errorReport,
  formatJqOutput,
  haltReport,
  jqCheck,
  jqOptions,
  jqRun,
  parseValue,
  readValues,
  referencesArgs,
  streamReads,
  type InputSource,
  type JqOptions,
  type JqRun,
  type StreamReads,
} from '../../../core/jq/index.ts'
import { yieldBytes } from '../../../io/stream.ts'
import { IOResult, materialize } from '../../../io/types.ts'
import { PathSpec } from '../../../types.ts'
import { mountKey, mountPrefixOf } from '../../../utils/key_prefix.ts'
import type { CommandFnResult, CommandOpts } from '../../config.ts'
import { UsageError } from '../../errors.ts'
import { isStdin, stdinStream } from '../utils/stream.ts'
import { readProgramFile } from './program.ts'

type Stream = (p: PathSpec) => AsyncIterable<Uint8Array>

const DEC = new TextDecoder()
const ENC = new TextEncoder()
const INDENT_MIN = -1
const INDENT_MAX = 7

// What jq's process() answers for one run, which its exit status is made
// of (main.c): the last output was not false or null, it was, there was
// none, and an error no `try` caught ended the run.
const OK = 0
const OK_NULL_KIND = -1
const OK_NO_OUTPUT = -4
const ERROR_UNKNOWN = 5

// jq's exit status when it refuses the program itself.
const ERROR_COMPILE = 3
const USAGE_HINT =
  'Use jq --help for help with command-line options,\n' +
  'or see the jq manpage, or online docs  at https://jqlang.github.io/jq'

/** Read a pair option's flattened values back as [name, value]. */
function pairArgs(values: readonly string[]): [string, string][] {
  const pairs: [string, string][] = []
  for (let i = 0; i + 1 < values.length; i += 2) {
    pairs.push([values[i] ?? '', values[i + 1] ?? ''])
  }
  return pairs
}

/** Collect the $name bindings from --arg and --argjson. */
export function namedArgs(fl: FlagView): Record<string, unknown> {
  const args: Record<string, unknown> = {}
  for (const [name, value] of pairArgs(fl.asList('arg'))) args[name] = value
  for (const [name, value] of pairArgs(fl.asList('argjson'))) {
    const parsed = parseValue(ENC.encode(value))
    if (parsed === NO_VALUE) {
      throw new UsageError(`jq: invalid JSON text passed to --argjson\n${USAGE_HINT}`, 2)
    }
    args[name] = parsed
  }
  return args
}

/**
 * Values `$ARGS.positional` reports, from --args / --jsonargs.
 *
 * The operands after the program stop being input files once either flag
 * appears, so they arrive here as ordinary text.
 */
export function positionalArgs(
  fl: FlagView,
  texts: readonly string[],
  hasProgramFile: boolean,
): unknown[] {
  const asJson = fl.asBool('jsonargs')
  if (!asJson && !fl.asBool('args')) return []
  const rest = hasProgramFile ? [...texts] : texts.slice(1)
  if (!asJson) return rest
  return rest.map((value) => {
    const parsed = parseValue(ENC.encode(value))
    if (parsed === NO_VALUE) {
      throw new UsageError(`jq: invalid JSON text passed to --jsonargs\n${USAGE_HINT}`, 2)
    }
    return parsed
  })
}

/**
 * Collect the $name bindings that read a file.
 *
 * --rawfile binds the file's text, --slurpfile the array of documents in
 * it, which is the same difference -R draws on the input stream. Both read
 * the bytes the way jq reads its inputs, and a --slurpfile holding bad JSON
 * is refused in jq's words with its parser's message.
 */
async function fileArgs(
  fl: FlagView,
  read: (value: string) => Promise<Uint8Array>,
): Promise<Record<string, unknown>> {
  const args: Record<string, unknown> = {}
  for (const [name, value] of pairArgs(fl.asList('rawfile'))) {
    args[name] = decodeUtf8(await read(value))
  }
  for (const [name, value] of pairArgs(fl.asList('slurpfile'))) {
    const [values, failure] = await readValues({
      name: value,
      chunks: yieldBytes(await read(value)),
    })
    if (failure !== null) {
      throw new UsageError(`jq: Bad JSON in --slurpfile ${name} ${value}: ${failure.message}`, 2)
    }
    args[name] = values
  }
  return args
}

/**
 * Read the raw jq flag kwargs into a frozen struct.
 *
 * Two deliberate divergences from jq's own parser, both from mirage
 * parsing a whole line before acting on it rather than one option at a
 * time. jq lets `-c`, `--tab` and `--indent` override each other in the
 * order typed; here `-c` wins whenever it appears. And jq reads a
 * non-numeric `--indent` as 0 (C atoi), where mirage refuses it like
 * every other int-typed option.
 */
export function parseFlags(fl: FlagView): JqOptions {
  const width = fl.asInt('indent')
  if (width !== undefined && (width < INDENT_MIN || width > INDENT_MAX)) {
    throw new UsageError(
      `jq: --indent takes a number between ${String(INDENT_MIN)} and ` +
        `${String(INDENT_MAX)}\n${USAGE_HINT}`,
      2,
    )
  }
  const joinOutput = fl.asBool('join_output')
  const nulOutput = fl.asBool('raw_output0')
  return jqOptions({
    nullInput: fl.asBool('null_input'),
    rawInput: fl.asBool('raw_input'),
    slurp: fl.asBool('slurp'),
    stream: fl.asBool('stream'),
    seq: fl.asBool('seq'),
    // -j and --raw-output0 are -r plus a different separator.
    rawOutput: fl.asBool('raw_output') || joinOutput || nulOutput,
    joinOutput,
    nulOutput,
    compact: fl.asBool('compact_output'),
    asciiOutput: fl.asBool('ascii_output'),
    sortKeys: fl.asBool('sort_keys'),
    // jq spells tab indentation both ways: --tab, or --indent -1.
    tab: fl.asBool('tab') || width === INDENT_MIN,
    indent: width === undefined || width === INDENT_MIN ? DEFAULT_INDENT : width,
    exitStatus: fl.asBool('exit_status'),
    namedArgs: namedArgs(fl),
  })
}

/** An input as jq's reports name it: the operand as typed, and `<stdin>` for `-`. */
export function inputName(path: PathSpec): string {
  if (path.rawPath === '-') return STDIN_NAME
  return path.rawPath === '' ? path.virtual : path.rawPath
}

/** What jq's process() answers for one run. */
export function runStatus(run: JqRun): number {
  if (run.stop?.kind === 'halt') return run.stop.code === null ? OK : Math.trunc(run.stop.code)
  if (run.stop?.kind === 'error') return ERROR_UNKNOWN
  if (run.outputs.length === 0) return OK_NO_OUTPUT
  const last = run.outputs[run.outputs.length - 1]
  return last === null || last === false ? OK_NULL_KIND : OK
}

/**
 * Exit status for the program run over the whole input, as jq's main loop
 * settles it from what each run answered (runStatus).
 *
 * Only the last run counts, even after one that failed, unless it printed
 * nothing, when -e looks back to the last value any run printed. Without
 * -e only a failure shows, and a halt's own code.
 */
export function exitCode(statuses: readonly number[], opts: JqOptions): number {
  let ret = OK_NO_OUTPUT
  let lastResult = -1
  for (const status of statuses) {
    ret = status
    if (status <= 0 && status !== OK_NO_OUTPUT) lastResult = status === OK_NULL_KIND ? 0 : 1
  }
  let code: number
  if (!opts.exitStatus) code = Math.max(ret, 0)
  else if (ret !== OK_NO_OUTPUT) code = Math.abs(ret)
  else code = lastResult === -1 ? 4 : lastResult === 0 ? 1 : 0
  return code % 256
}

/**
 * jq's report of a parse error its main loop meets: fatal, or under --seq a
 * line it prints before reading on.
 */
export function parseReport(failure: JqParseError, opts: JqOptions): string {
  const kind = opts.seq ? 'ignoring parse error' : 'parse error'
  return `jq: ${kind}: ${failure.message}\n`
}

/**
 * Open an input now, so a missing file fails the command before it prints
 * anything, while its bytes still stream as they are read.
 */
async function opened(chunks: AsyncIterable<Uint8Array>): Promise<AsyncIterable<Uint8Array>> {
  const iterator = chunks[Symbol.asyncIterator]()
  const first = await iterator.next()
  return resumed(first, iterator)
}

async function* resumed(
  first: IteratorResult<Uint8Array>,
  rest: AsyncIterator<Uint8Array>,
): AsyncIterable<Uint8Array> {
  if (first.done === true) return
  yield first.value
  for (;;) {
    const next = await rest.next()
    if (next.done === true) return
    yield next.value
  }
}

/**
 * jq's main loop (main.c) over an invocation's input stream.
 *
 * Each document runs as soon as the reader parses it, and its outputs stream
 * out. A run's error is reported and the next document runs; a halt ends the
 * loop; a parse error is reported with status 5 and ends it, except under
 * --seq, which reports it and reads on. Under -n the program runs once, on
 * null. The exit status and stderr settle on `io` once the stream is
 * drained.
 *
 * A run of a program that calls `input` or `inputs` reads what they take
 * before the program runs (see run), and nothing past it, so the loop never
 * reads further ahead than jq's own.
 */
export class MainLoop {
  private readonly statuses: number[] = []
  private readonly reports: string[] = []

  constructor(
    private readonly reader: InputReader,
    private readonly expr: string,
    private readonly opts: JqOptions,
    private readonly reads: StreamReads,
    private readonly argsValue: Record<string, unknown> | null,
    private readonly io: IOResult,
  ) {}

  /** The invocation's stdout, run by run. */
  async *outputs(): AsyncIterable<Uint8Array> {
    try {
      if (this.opts.nullInput) {
        const [run, position] = await this.run(null, this.reader.position())
        if (run.outputs.length > 0) yield formatJqOutput(run.outputs, this.opts)
        this.settle(run, position)
        return
      }
      for (;;) {
        const item = await this.reader.nextInput()
        if (item === NO_VALUE) return
        if (item instanceof JqParseError) {
          this.fail(item)
          if (this.opts.seq) continue
          return
        }
        const [run, position] = await this.run(item, this.reader.position())
        if (run.outputs.length > 0) yield formatJqOutput(run.outputs, this.opts)
        if (this.settle(run, position)) return
      }
    } finally {
      this.io.exitCode = exitCode(this.statuses, this.opts)
      if (this.reports.length > 0) this.io.stderr = ENC.encode(this.reports.join(''))
    }
  }

  /**
   * Run the program on one document (null under -n), and say where the
   * reader stands after it, for its error report; `position` is where it
   * stood once it had read the document.
   *
   * `input` and `inputs` consume the stream the main loop reads, so a run
   * reads what they take first, and the next run starts past it. How much a
   * run takes is a runtime fact this evaluator does not report, so mirage
   * assumes what the idioms do: `inputs` drains the rest (`[., inputs]`,
   * `reduce inputs as $x`), and `input` alone takes one (`[., input]` pairs
   * the documents up). A program that takes some other count
   * (`first(inputs)`, an `input` in a branch not taken) leaves real jq a
   * different remainder for its next run than here. A parse error stops the
   * reading: the run raises it where `input` or `inputs` would reach it, and
   * the main loop reads on past it.
   */
  private async run(doc: unknown, position: string): Promise<[JqRun, string]> {
    const reads = this.reads
    if (!reads.input && !reads.inputs) {
      return [await jqRun(doc, this.expr, this.opts.namedArgs, null, this.argsValue), position]
    }
    const docs: unknown[] = []
    let failure: JqParseError | null = null
    let at = position
    for (;;) {
      const item = await this.reader.nextInput()
      at = this.reader.position()
      if (item === NO_VALUE) break
      if (item instanceof JqParseError) {
        failure = item
        break
      }
      docs.push(item)
      if (!reads.inputs) break
    }
    const run = await jqRun(
      doc,
      this.expr,
      this.opts.namedArgs,
      docs,
      this.argsValue,
      failure === null ? null : failure.message,
    )
    return [run, at]
  }

  // Fold one run into the invocation: its answer toward the exit status,
  // and its report when it stopped early. A halt ends the invocation, which
  // is what this answers.
  private settle(run: JqRun, position: string): boolean {
    this.statuses.push(runStatus(run))
    if (run.stop?.kind === 'error') {
      this.reports.push(errorReport(position, run.stop))
    } else if (run.stop?.kind === 'halt') {
      this.reports.push(haltReport(run.stop))
      return true
    }
    return false
  }

  // jq's `ret = JQ_ERROR_UNKNOWN; break`, or under --seq a report that
  // leaves the status alone.
  private fail(failure: JqParseError): void {
    this.reports.push(parseReport(failure, this.opts))
    if (!this.opts.seq) this.statuses.push(ERROR_UNKNOWN)
  }
}

// Path flags arrive as resolved virtual-path strings, so a flag that
// names a file builds its own PathSpec against the operands' mount.
function pathSpecFactory(
  paths: readonly PathSpec[],
  opts: CommandOpts,
): (value: string) => PathSpec {
  const first = paths[0]
  const mountPrefix =
    (first === undefined ? undefined : mountPrefixOf(first.virtual, first.vfsPath)) ??
    opts.mountPrefix ??
    ''
  return (value) => PathSpec.fromStrPath(value, mountKey(value, mountPrefix))
}

async function programText(
  texts: readonly string[],
  fl: FlagView,
  toSpec: (value: string) => PathSpec,
  stream: Stream,
): Promise<string> {
  const fromFile = fl.asStr('from_file')
  // jq defaults the filter to "." when no expression is given.
  if (fromFile === undefined) return texts[0] ?? '.'
  return DEC.decode(await materialize(stream(toSpec(fromFile))))
}

export async function jqGeneric(
  paths: PathSpec[],
  texts: string[],
  opts: CommandOpts,
  stream: Stream,
): Promise<CommandFnResult> {
  stream = stdinStream(stream, opts.stdin)
  const fl = new FlagView(opts.flags, specOf('jq'))
  const toSpec = pathSpecFactory(paths, opts)
  const hasProgramFile = fl.asStr('from_file') !== undefined
  const expr = (await programText(texts, fl, toSpec, stream)).trim()
  const reads = streamReads(expr)
  const readsStream = reads.input || reads.inputs
  // --rawfile / --slurpfile read a file each, so they join the bindings
  // only once a reader is in hand. Their files route nothing (the executor's
  // DOOR_FLAG_KEYS), so one may sit on another mount than the operands: it
  // is read through the door, stdin excepted, which is the invocation's own.
  const readFlagFile = (value: string): Promise<Uint8Array> => {
    const path = toSpec(value)
    if (opts.dispatch === undefined || isStdin(path)) return materialize(stream(path))
    return readProgramFile('jq', path, opts.dispatch)
  }
  const base = parseFlags(fl)
  const jq: JqOptions = jqOptions({
    ...base,
    namedArgs: { ...base.namedArgs, ...(await fileArgs(fl, readFlagFile)) },
    positionalArgs: positionalArgs(fl, texts, hasProgramFile),
  })
  const argsValue = referencesArgs(expr) ? argsObject(jq) : null
  try {
    await jqCheck(expr, jq.namedArgs, readsStream ? [] : null, argsValue)
  } catch (error) {
    if (!(error instanceof JqCompileError)) throw error
    // jq compiles its program before it opens a single input, so a
    // refusal is all it prints.
    return [
      null,
      new IOResult({
        exitCode: ERROR_COMPILE,
        stderr: new TextEncoder().encode(`${error.message}\n`),
      }),
    ]
  }

  const sources: InputSource[] = []
  // -n does not read its inputs at all unless the program asks for them
  // through `input` or `inputs`, which is why jq -n never opens a missing
  // file.
  if (!jq.nullInput || readsStream) {
    if (paths.length > 0) {
      for (const path of paths) {
        sources.push({ name: inputName(path), chunks: await opened(stream(path)) })
      }
    } else if (opts.stdin !== null) {
      const stdin = opts.stdin
      sources.push({
        name: STDIN_NAME,
        chunks: stdin instanceof Uint8Array ? yieldBytes(stdin) : stdin,
      })
    }
  }
  const io = new IOResult()
  const loop = new MainLoop(new InputReader(sources, jq), expr, jq, reads, argsValue, io)
  return [loop.outputs(), io]
}
