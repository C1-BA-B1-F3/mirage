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
  InputPositions,
  JqCompileError,
  STDIN_NAME,
  UNKNOWN_POSITION,
  argsObject,
  errorReport,
  evalJsonlStream,
  formatJqOutput,
  haltReport,
  halts,
  isJsonlPath,
  isStreamableJsonlExpr,
  jqCheck,
  jqOptions,
  jqRun,
  parseJsonDocs,
  parseJsonText,
  parseSeqText,
  referencesArgs,
  splitRawText,
  streamEvents,
  streamReads,
  type JqOptions,
  type JqRun,
  type StreamReads,
} from '../../../core/jq/index.ts'
import { IOResult, materialize, type ByteSource } from '../../../io/types.ts'
import { PathSpec } from '../../../types.ts'
import { mountKey, mountPrefixOf } from '../../../utils/key_prefix.ts'
import type { CommandFnResult, CommandOpts } from '../../config.ts'
import { UsageError } from '../../errors.ts'
import { isStdin, readStdinAsync, stdinStream } from '../utils/stream.ts'
import { readProgramFile } from './program.ts'

type Stream = (p: PathSpec) => AsyncIterable<Uint8Array>

const DEC = new TextDecoder()
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
    try {
      args[name] = JSON.parse(value) as unknown
    } catch {
      throw new UsageError(`jq: invalid JSON text passed to --argjson\n${USAGE_HINT}`, 2)
    }
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
    try {
      return JSON.parse(value) as unknown
    } catch {
      throw new UsageError(`jq: invalid JSON text passed to --jsonargs\n${USAGE_HINT}`, 2)
    }
  })
}

/**
 * Collect the $name bindings that read a file.
 *
 * --rawfile binds the file's text, --slurpfile the array of documents in
 * it, which is the same difference -R draws on the input stream.
 */
async function fileArgs(
  fl: FlagView,
  read: (value: string) => Promise<Uint8Array>,
): Promise<Record<string, unknown>> {
  const args: Record<string, unknown> = {}
  for (const [name, value] of pairArgs(fl.asList('rawfile'))) {
    args[name] = DEC.decode(await read(value))
  }
  for (const [name, value] of pairArgs(fl.asList('slurpfile'))) {
    args[name] = parseJsonDocs(await read(value))
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

/**
 * Turn the raw inputs into the value stream the program sees, and say
 * where jq's reader stands once it has read each value.
 *
 * jq reads every file and stdin as one stream, so slurping spans them all
 * rather than restarting per file. Line splitting stays per input: a file
 * with no trailing newline ends its last line there instead of joining it
 * to the next file's first. `sources` are each input's name, as jq reports
 * it, and its bytes, in order.
 */
export async function assembleInputs(
  sources: readonly (readonly [string, Uint8Array])[],
  opts: JqOptions,
): Promise<[unknown[], InputPositions]> {
  const names = sources.map(([name]) => name)
  const texts = sources.map(([, raw]) => DEC.decode(raw))
  let docs: unknown[] = []
  let marks: [number, number][] = []
  if (opts.rawInput && opts.slurp) {
    docs.push(texts.join(''))
  } else if (opts.rawInput) {
    texts.forEach((text, i) => {
      const [lines, ends] = splitRawText(text)
      docs.push(...lines)
      for (const end of ends) marks.push([i, end])
    })
  } else {
    const parse = opts.seq ? parseSeqText : parseJsonText
    texts.forEach((text, i) => {
      const [values, ends] = parse(text)
      docs.push(...values)
      for (const end of ends) marks.push([i, end])
    })
    if (opts.stream) {
      // --stream replaces each document with its events, and slurping
      // then collects the events rather than the documents. Each event
      // reads as where its document is whole, where jq's streaming parser
      // hands events over as it goes.
      const events = await Promise.all(docs.map((doc) => streamEvents(doc)))
      docs = events.flat()
      const own = marks
      marks = events.flatMap((group, i) => group.map((): [number, number] => own[i] ?? [0, 0]))
    }
    if (opts.slurp) docs = [docs]
  }
  if (opts.slurp) {
    // One value, and whole only once every input is read.
    const last = texts.length - 1
    marks = last < 0 ? [] : [[last, texts[last]?.length ?? 0]]
  }
  return [docs, new InputPositions(names, texts, marks)]
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
 * Where jq's reader stands after a run, for its error report. A run reads
 * its own document (`first`, null under -n), and past it the ones `input`
 * and `inputs` take (`taken`): `inputs` reads to the end, and so does an
 * `input` that finds nothing left.
 */
export function runPosition(
  positions: InputPositions,
  reads: StreamReads,
  first: number | null,
  taken: number,
): string {
  if (reads.inputs || (reads.input && taken === 0)) return positions.end()
  if (reads.input) return positions.at(first === null ? 0 : first + 1)
  return first === null ? UNKNOWN_POSITION : positions.at(first)
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

  // The per-line path rewrites the program to run on one element, so it
  // can only serve a run whose input stream is the file's documents and
  // whose exit code does not depend on the last of them. A halt reports on
  // stderr and sets the exit code, which a stream of outputs has no room
  // for.
  const first = paths[0]
  if (
    first !== undefined &&
    isJsonlPath(first.virtual) &&
    isStreamableJsonlExpr(expr) &&
    !jq.nullInput &&
    !jq.rawInput &&
    !jq.slurp &&
    !jq.stream &&
    !jq.seq &&
    !jq.exitStatus &&
    !readsStream &&
    !halts(expr)
  ) {
    return [
      evalJsonlStream(
        stream(first),
        expr,
        jq,
        first.rawPath === '' ? first.virtual : first.rawPath,
      ),
      new IOResult(),
    ]
  }

  const sources: [string, Uint8Array][] = []
  // -n does not read its inputs at all unless the program asks for them
  // through `input` or `inputs`, which is why jq -n never opens a missing
  // file.
  if (!jq.nullInput || readsStream) {
    if (paths.length > 0) {
      for (const path of paths) {
        sources.push([
          path.rawPath === '' ? path.virtual : path.rawPath,
          await materialize(stream(path)),
        ])
      }
    } else {
      const stdinBytes = await readStdinAsync(opts.stdin)
      if (stdinBytes !== null) sources.push([STDIN_NAME, stdinBytes])
    }
  }
  const [docs, positions] = await assembleInputs(sources, jq)

  // A run sees only the documents it can read: all of the rest when it
  // calls `inputs`, or the one `input` takes when it calls only that.
  const unread = (at: number): unknown[] => (reads.inputs ? docs.slice(at) : docs.slice(at, at + 1))
  const outputs: unknown[] = []
  const statuses: number[] = []
  const reports: string[] = []
  // Fold one run into the invocation: its outputs, its answer toward the
  // exit status, and its report when it stopped early. A halt ends the
  // invocation, which is what this answers.
  const settle = (run: JqRun, at: number | null, taken: number): boolean => {
    outputs.push(...run.outputs)
    statuses.push(runStatus(run))
    if (run.stop?.kind === 'error') {
      reports.push(errorReport(runPosition(positions, reads, at, taken), run.stop))
    } else if (run.stop?.kind === 'halt') {
      reports.push(haltReport(run.stop))
      return true
    }
    return false
  }
  if (jq.nullInput) {
    const rest = readsStream ? unread(0) : null
    settle(await jqRun(null, expr, jq.namedArgs, rest, argsValue), null, rest?.length ?? 0)
  } else if (readsStream) {
    // `input` and `inputs` consume from the same stream the main loop
    // reads, so each run starts past whatever the one before it took. How
    // much a run takes is a runtime fact this evaluator does not report,
    // so mirage assumes what the idioms do: `inputs` drains the rest
    // (`[., inputs]`, `reduce inputs as $x`), and `input` alone takes one
    // (`[., input]` pairs the documents up). A program that takes some
    // other count (`first(inputs)`, an `input` in a branch not taken)
    // leaves real jq a different remainder for its next run than here.
    let at = 0
    while (at < docs.length) {
      const rest = unread(at + 1)
      if (settle(await jqRun(docs[at], expr, jq.namedArgs, rest, argsValue), at, rest.length)) break
      at += 1 + rest.length
    }
  } else {
    // jq applies the program to every document in the stream, and goes on
    // past one whose run failed.
    for (const [at, doc] of docs.entries()) {
      if (settle(await jqRun(doc, expr, jq.namedArgs, null, argsValue), at, 0)) break
    }
  }
  const out: ByteSource = formatJqOutput(outputs, jq)
  const stderr = reports.length > 0 ? new TextEncoder().encode(reports.join('')) : null
  return [out, new IOResult({ exitCode: exitCode(statuses, jq), stderr })]
}
