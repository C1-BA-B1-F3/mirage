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

import { SHELL_SPECS, parseShellOptions } from '../../../../commands/spec/shell.ts'
import { IOResult, materialize } from '../../../../io/types.ts'
import type { ByteSource } from '../../../../io/types.ts'
import { asyncChain } from '../../../../io/stream.ts'
import { shellJoin } from '../../../../shell/join.ts'
import type { SessionState } from '../../../session/session.ts'
import { ExecutionNode } from '../../../types.ts'
import type { BuiltinCall, ExecuteStringFn, Result } from '../types.ts'

const UNSUPPORTED = ['P']
const BLANKS = new Set([' ', '\t'])
const SPACES = new Set([' ', '\t', '\n', '\v', '\f', '\r'])
const QUOTES = new Map([
  ["'", 'single'],
  ['"', 'double'],
])
const NUMBER = /^[ \t\n\v\f\r]*[+-]?[0-9]+$/

type ReadState = 'norm' | 'space' | 'quote' | 'backslash'
type Read = [words: string[], counted: boolean]

function usageError(message: string): Result {
  const stderr = new TextEncoder().encode(`xargs: ${message}\n`)
  return [
    null,
    new IOResult({ exitCode: 1, stderr }),
    new ExecutionNode({ command: 'xargs', exitCode: 1 }),
  ]
}

/** GNU's refusal of a -n or -L count, null for a valid one. */
function countError(raw: string, name: string): string | null {
  if (!NUMBER.test(raw)) return `invalid number "${raw}" for -${name} option`
  if (Number(raw.trim()) < 1) return `value ${raw} for -${name} option should be >= 1`
  return null
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
 * Run a command with words read from stdin (GNU xargs).
 *
 * The words are appended to the initial arguments, or with -I each
 * input line takes the place of the string in them. -I, -L and -n
 * cancel each other, the later one winning with GNU's warning; an
 * option given twice counts where it was last given, so it warns once
 * where GNU warns for each occurrence.
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
  if (parse.invalid !== null) {
    if (parse.invalid.startsWith('--')) return usageError(`unrecognized option '${parse.invalid}'`)
    return usageError(`invalid option -- '${parse.invalid}'`)
  }
  if (parse.needsValue !== null) {
    return usageError(`option requires an argument -- '${parse.needsValue}'`)
  }
  for (const name of UNSUPPORTED) {
    if (name in parse.flags) return usageError(`unsupported option -- '${name}'`)
  }
  let replace: string | null = null
  let maxLines = 0
  let maxArgs = 0
  const warnings: string[] = []
  for (const [name, value] of Object.entries(parse.flags)) {
    if (typeof value !== 'string' || !['I', 'L', 'n'].includes(name)) continue
    if (name === 'I') {
      if (maxArgs > 0) warnings.push(exclusive('--replace/-I/-i', '--max-args'))
      if (maxLines > 0) warnings.push(exclusive('--replace/-I/-i', '--max-lines'))
      replace = value
      maxLines = 0
      maxArgs = 0
      continue
    }
    const error = countError(value, name)
    if (error !== null) return usageError(error)
    const count = Number(value.trim())
    if (name === 'L') {
      if (maxArgs > 0) warnings.push(exclusive('-L', '--max-args'))
      if (replace !== null) warnings.push(exclusive('-L', '--replace'))
      replace = null
      maxLines = count
      maxArgs = 0
      continue
    }
    if (maxLines > 0) warnings.push(exclusive('--max-args/-n', '--max-lines'))
    maxLines = 0
    // GNU reads `-I {} -n1` as plain -I.
    if (replace !== null && count === 1) continue
    if (replace !== null) warnings.push(exclusive('--max-args/-n', '--replace'))
    replace = null
    maxArgs = count
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
      return usageError('command too long')
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

  const stdouts: ByteSource[] = []
  const warned = warnings.join('')
  let merged = new IOResult(warned === '' ? {} : { stderr: new TextEncoder().encode(warned) })
  let exitCode = 0
  for (const run of runs) {
    const io = await executeFn(shellJoin(run), { sessionId: session.sessionId })
    if (io.stdout !== null) stdouts.push(io.stdout)
    merged = await merged.merge(io)
    if (io.exitCode === 126 || io.exitCode === 127) {
      // GNU xargs stops when the command cannot run or is missing.
      exitCode = io.exitCode
      break
    }
    if (io.exitCode !== 0) {
      // GNU exits 123 when any invocation fails, but keeps going.
      exitCode = 123
    }
  }
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
