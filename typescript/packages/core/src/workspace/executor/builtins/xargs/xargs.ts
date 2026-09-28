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

import { versionLine } from '../../../../commands/config.ts'
import { runWithSession } from '../../../../context/session_context.ts'
import { renderHelp } from '../../../../commands/spec/help.ts'
import { SHELL_SPECS, parseShellOptions } from '../../../../commands/spec/shell.ts'
import {
  missingValueError,
  unknownOptionError,
  usageHint,
} from '../../../../commands/spec/usage.ts'
import { IOResult, materialize } from '../../../../io/types.ts'
import type { ByteSource } from '../../../../io/types.ts'
import { asyncChain, yieldBytes } from '../../../../io/stream.ts'
import { shellJoin } from '../../../../shell/join.ts'
import { asyncContextIsolatesTasks } from '../../../../utils/async_context.ts'
import type { SessionState } from '../../../session/session.ts'
import { ExecutionNode } from '../../../types.ts'
import type { BuiltinCall, ExecuteStringFn, Result } from '../types.ts'

const SYNOPSIS = 'xargs [OPTION]... COMMAND [INITIAL-ARGS]...'
const PROCS_MAX = 2147483647
const BLANKS = new Set([' ', '\t'])
const SPACES = new Set([' ', '\t', '\n', '\v', '\f', '\r'])
const QUOTES = new Map([
  ["'", 'single'],
  ['"', 'double'],
])
const NUMBER = /^[ \t\n\v\f\r]*[+-]?[0-9]+$/

type ReadState = 'norm' | 'space' | 'quote' | 'backslash'
type Read = [words: string[], counted: boolean]

function refuse(stderr: string | Uint8Array, exitCode = 1): Result {
  const data = typeof stderr === 'string' ? new TextEncoder().encode(stderr) : stderr
  return [
    null,
    new IOResult({ exitCode, stderr: data }),
    new ExecutionNode({ command: 'xargs', exitCode }),
  ]
}

function concat(head: string, tail: Uint8Array): Uint8Array {
  const lead = new TextEncoder().encode(head)
  const out = new Uint8Array(lead.length + tail.length)
  out.set(lead)
  out.set(tail, lead.length)
  return out
}

/** GNU's parse_num refusal of a count, null for a valid one. */
function countError(
  raw: string,
  name: string,
  least = 1,
  most: number | null = null,
): string | null {
  let message: string
  if (!NUMBER.test(raw)) message = `invalid number "${raw}" for -${name} option`
  else if (Number(raw.trim()) < least)
    message = `value ${raw} for -${name} option should be >= ${String(least)}`
  else if (most !== null && Number(raw.trim()) > most) {
    message = `value ${raw} for -${name} option should be <= ${String(most)}`
  } else return null
  return `xargs: ${message}\n${usageHint('xargs')}\n`
}

/** xargs's answer to --help or --version: stdout, exit 0. */
function standardResponse(option: string, warnings: string): Result {
  const text =
    option === 'help'
      ? renderHelp('xargs', SHELL_SPECS.xargs, [], undefined, SYNOPSIS)
      : versionLine('xargs')
  return [
    yieldBytes(new TextEncoder().encode(text)),
    new IOResult(warnings === '' ? {} : { stderr: new TextEncoder().encode(warnings) }),
    new ExecutionNode({ command: 'xargs', exitCode: 0 }),
  ]
}

function exclusive(option: string, offending: string): string {
  return `xargs: warning: options ${offending} and ${option} are mutually exclusive, ignoring previous ${offending} value\n`
}

function delimiter(flags: Record<string, string | boolean>): string | null {
  if (flags['0'] === true) return '\0'
  const delim = flags.d
  if (typeof delim === 'string') return delim.replace(/\\n/g, '\n').replace(/\\t/g, '\t')
  return null
}

/** GNU's read_string: every delimiter ends an item, empty ones too. */
function readItems(text: string, delim: string): string[] {
  const items = text.split(delim)
  if (items[items.length - 1] === '') items.pop()
  return items
}

function unmatched(quote: string): string {
  return `xargs: unmatched ${QUOTES.get(quote) ?? ''} quote; by default quotes are special to xargs unless you use the -0 option\n`
}

/**
 * GNU's read_line over the whole input.
 *
 * One entry per read: the words it pushed and whether the newline
 * ending it counts as a line for -L. Blanks separate words and a
 * newline ends the read; quotes and backslashes are removed; leading
 * blanks and blank lines are skipped, and a line whose last character
 * is a blank runs on into the next one. Under -I only a newline ends
 * the word, so the read is the whole line. An unmatched quote ends the
 * reading with GNU's refusal, after the reads before it and the words
 * its own read had pushed; the refusal is empty otherwise.
 */
function readLines(text: string, replace: boolean): [Read[], string] {
  const reads: Read[] = []
  let words: string[] = []
  let buf = ''
  let state: ReadState = 'space'
  let quote = ''
  let prev = ''
  for (const c of text) {
    const before = prev
    prev = c
    if (state === 'space') {
      if (SPACES.has(c)) continue
      state = 'norm'
    }
    if (state === 'norm') {
      if (c === '\n') {
        words.push(buf)
        reads.push([words, !BLANKS.has(before)])
        words = []
        buf = ''
        state = 'space'
        continue
      }
      if (!replace && BLANKS.has(c)) {
        words.push(buf)
        buf = ''
        state = 'space'
        continue
      }
      if (c === '\\') {
        state = 'backslash'
        continue
      }
      if (QUOTES.has(c)) {
        state = 'quote'
        quote = c
        continue
      }
    } else if (state === 'quote') {
      if (c === '\n') {
        reads.push([words, false])
        return [reads, unmatched(quote)]
      }
      if (c === quote) {
        state = 'norm'
        continue
      }
    } else {
      state = 'norm'
    }
    buf += c
  }
  if (buf !== '' && state === 'quote') {
    reads.push([words, false])
    return [reads, unmatched(quote)]
  }
  if (buf !== '') words.push(buf)
  if (words.length > 0) reads.push([words, false])
  return [reads, '']
}

/**
 * GNU's exec points without -I, and the words left pending.
 *
 * A batch runs once it holds -n words or -L lines.
 */
function batchReads(reads: Read[], maxLines: number, maxArgs: number): [string[][], string[]] {
  const batches: string[][] = []
  let pending: string[] = []
  let lines = 0
  for (const [words, counted] of reads) {
    for (const word of words) {
      pending.push(word)
      if (maxArgs > 0 && pending.length === maxArgs) {
        batches.push(pending)
        pending = []
      }
    }
    if (counted) lines += 1
    if (maxLines > 0 && lines >= maxLines) {
      batches.push(pending)
      pending = []
      lines = 0
    }
  }
  return [batches, pending]
}

/**
 * Run the command lines, at most `procs` at a time.
 *
 * GNU starts no command once one could not run (126, 127) and waits for
 * those already running. Commands that run side by side each get a fork
 * of the session, as GNU's children are separate processes, so one
 * cannot see another's variables, and each drains inside its fork, since
 * a stream can still read the ambient session. Where the async context
 * cannot keep concurrent forks apart (a browser without
 * AsyncLocalStorage) the lines run one at a time, as a background job's
 * nested evals fall back there. The results come back in input order,
 * which is the order their output is written in.
 */
async function runLines(
  executeFn: ExecuteStringFn,
  lines: string[],
  session: SessionState,
  procs: number,
): Promise<IOResult[]> {
  const results: (IOResult | null)[] = lines.map(() => null)
  let next = 0
  let stopped = false
  const forked = procs !== 1 && lines.length > 1 && asyncContextIsolatesTasks
  const run = async (line: string): Promise<IOResult> => {
    if (!forked) return executeFn(line, { sessionId: session.sessionId })
    return runWithSession(session.fork(), async () => {
      const io = await executeFn(line, { sessionId: session.sessionId })
      await io.materializeStdout()
      await io.materializeStderr()
      return io
    })
  }
  const worker = async (): Promise<void> => {
    while (!stopped && next < lines.length) {
      const index = next
      next += 1
      let io: IOResult
      try {
        io = await run(lines[index] ?? '')
      } catch (err) {
        stopped = true
        throw err
      }
      results[index] = io
      if (io.exitCode === 126 || io.exitCode === 127) stopped = true
    }
  }
  const width = forked ? (procs === 0 ? lines.length : Math.min(procs, lines.length)) : 1
  await Promise.all(Array.from({ length: width }, worker))
  return results.filter((io): io is IOResult => io !== null)
}

/**
 * Run a command with words read from stdin (GNU xargs).
 *
 * The words are appended to the initial arguments, or with -I each
 * input line takes the place of the string in them. Options act in the
 * order given, as GNU's getopt loop reads them: -I, -L and -n cancel
 * each other with GNU's warning, and --help or --version answers where
 * it stands.
 *
 * GNU xargs execs the command directly, so every input word must reach
 * it as exactly one argv token. The inner line is built with shellJoin:
 * a plain join would be re-parsed by the shell, splitting words with
 * whitespace and executing $(...) found in input.
 */
export async function handleXargs(
  executeFn: ExecuteStringFn,
  args: readonly string[],
  session: SessionState,
  stdin: ByteSource | null,
): Promise<Result> {
  const parse = parseShellOptions(SHELL_SPECS.xargs, args)
  let replace: string | null = null
  let maxLines = 0
  let maxArgs = 0
  let procs = 1
  let warnings = ''
  for (const [name, value] of parse.given) {
    if (name === 'help' || name === 'version') return standardResponse(name, warnings)
    if (name === 'I' || name === 'i') {
      if (maxArgs > 0) warnings += exclusive('--replace/-I/-i', '--max-args')
      if (maxLines > 0) warnings += exclusive('--replace/-I/-i', '--max-lines')
      replace = typeof value === 'string' ? value : '{}'
      maxLines = 0
      maxArgs = 0
      continue
    }
    if (!['L', 'l', 'n', 'P'].includes(name)) continue
    const raw = typeof value === 'string' ? value : '1'
    const error = name === 'P' ? countError(raw, name, 0, PROCS_MAX) : countError(raw, name)
    if (error !== null) return refuse(warnings + error)
    const count = Number(raw.trim())
    if (name === 'P') {
      procs = count
      continue
    }
    if (name === 'L' || name === 'l') {
      const option = name === 'L' ? '-L' : '--max-lines/-l'
      if (maxArgs > 0) warnings += exclusive(option, '--max-args')
      if (replace !== null) warnings += exclusive(option, '--replace')
      replace = null
      maxLines = count
      maxArgs = 0
      continue
    }
    if (maxLines > 0) warnings += exclusive('--max-args/-n', '--max-lines')
    maxLines = 0
    // GNU reads `-I {} -n1` as plain -I.
    if (replace !== null && count === 1) continue
    if (replace !== null) warnings += exclusive('--max-args/-n', '--replace')
    replace = null
    maxArgs = count
  }
  if (parse.invalid !== null) {
    const [stderr, code] = unknownOptionError('xargs', parse.invalid)
    return refuse(concat(warnings, stderr), code)
  }
  if (parse.needsValue !== null) {
    const [stderr, code] = missingValueError('xargs', parse.needsValue)
    return refuse(concat(warnings, stderr), code)
  }

  const text = new TextDecoder().decode(await materialize(stdin))
  const delim = delimiter(parse.flags)
  const [reads, quoteError]: [Read[], string] =
    delim === null
      ? readLines(text, replace !== null)
      : [readItems(text, delim).map((item): Read => [[item], true]), '']

  const command = parse.operands.length > 0 ? parse.operands : ['echo']
  const runs: string[][] = []
  if (replace !== null) {
    const pattern = replace
    const items = reads.flatMap(([words]) => words)
    if (items.length > 0 && pattern === '' && command.length > 1) {
      return refuse(`${warnings}xargs: command too long\n`)
    }
    const [head = 'echo', ...initial] = command
    for (const item of items) {
      runs.push([head, ...initial.map((arg) => arg.replaceAll(pattern, () => item))])
    }
  } else {
    const [batches, pending] = batchReads(reads, maxLines, maxArgs)
    if (quoteError !== '') {
      // GNU runs what it had read unless -L holds whole lines.
      if (pending.length > 0 && maxLines === 0) batches.push(pending)
    } else if (pending.length > 0 || !(batches.length > 0 || parse.flags.r === true)) {
      batches.push(pending)
    }
    for (const batch of batches) runs.push([...command, ...batch])
  }

  const ios = await runLines(executeFn, runs.map(shellJoin), session, procs)
  const stdouts: ByteSource[] = []
  let merged = new IOResult(warnings === '' ? {} : { stderr: new TextEncoder().encode(warnings) })
  for (const io of ios) {
    if (io.stdout !== null) stdouts.push(io.stdout)
    merged = await merged.merge(io)
  }
  // GNU xargs stops when the command cannot run or is missing, and exits
  // 123 when any invocation fails but keeps going.
  const stop = ios.find((io) => io.exitCode === 126 || io.exitCode === 127)
  let exitCode = stop !== undefined ? stop.exitCode : ios.some((io) => io.exitCode !== 0) ? 123 : 0
  if (quoteError !== '' && exitCode !== 126 && exitCode !== 127) {
    merged = await merged.merge(new IOResult({ stderr: new TextEncoder().encode(quoteError) }))
    exitCode = 1
  }
  merged.exitCode = exitCode
  const out = stdouts.length > 0 ? asyncChain(...stdouts) : null
  return [out, merged, new ExecutionNode({ command: 'xargs', exitCode })]
}

/** The `xargs` arm. */
export async function xargsBuiltin(call: BuiltinCall): Promise<Result> {
  return handleXargs(call.executeFn, [...call.argv.args], call.session, call.stdin)
}
