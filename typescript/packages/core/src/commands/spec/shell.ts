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

import { HELP_OPTION, VERSION_OPTION } from './constants.ts'
import { CommandSpec, Operand, Option } from './types.ts'

export const SHELL_SPECS = Object.freeze({
  xargs: new CommandSpec({
    description: 'Build and run command lines from standard input.',
    options: [
      new Option({
        short: '-n',
        long: '--max-args',
        type: 'str',
        description: 'Use at most N arguments per command line.',
      }),
      new Option({
        short: '-d',
        long: '--delimiter',
        type: 'str',
        description: 'Input items are separated by this character.',
      }),
      new Option({
        short: '-0',
        long: '--null',
        description: 'Input items are terminated by NUL.',
      }),
      new Option({
        short: '-r',
        long: '--no-run-if-empty',
        description: 'Do not run the command on empty input.',
      }),
      new Option({
        short: '-I',
        type: 'str',
        description: 'Replace this string in the initial arguments with each input line.',
      }),
      new Option({
        short: '-i',
        long: '--replace',
        type: 'str',
        valueOptional: true,
        description: 'Same as -I, with {} when no string is attached.',
      }),
      new Option({
        short: '-L',
        type: 'str',
        description: 'Use at most N non-blank input lines per command line.',
      }),
      new Option({
        short: '-l',
        long: '--max-lines',
        type: 'str',
        valueOptional: true,
        description: 'Same as -L, with 1 when no count is attached.',
      }),
      new Option({
        short: '-P',
        long: '--max-procs',
        type: 'str',
        description: 'Run up to N commands at a time; 0 runs them all at once.',
      }),
      HELP_OPTION,
      VERSION_OPTION,
    ],
    rest: new Operand({ type: 'str' }),
  }),
  timeout: new CommandSpec({
    description: 'Run a command with a time limit.',
    options: [
      new Option({
        short: '-s',
        long: '--signal',
        type: 'str',
        description: 'Signal to send on timeout (not supported).',
      }),
      new Option({
        short: '-k',
        long: '--kill-after',
        type: 'str',
        description: 'Also send KILL after this long (not supported).',
      }),
      new Option({
        long: '--preserve-status',
        description: "Exit with the command's status on timeout (not supported).",
      }),
    ],
    rest: new Operand({ type: 'str' }),
  }),
  read: new CommandSpec({
    description: 'Read a line from standard input into variables.',
    options: [
      new Option({ short: '-r', description: 'Raw mode: backslash is not an escape character.' }),
      new Option({ short: '-a', type: 'str', description: 'Store the words in the named array.' }),
      new Option({ short: '-d', type: 'str', description: 'Read up to this character.' }),
      new Option({ short: '-n', type: 'str', description: 'Return after at most N characters.' }),
      new Option({ short: '-N', type: 'str', description: 'Return after exactly N characters.' }),
      new Option({ short: '-t', type: 'str', description: 'Time out after N seconds.' }),
      new Option({ short: '-p', type: 'str', description: 'Prompt (terminal only).' }),
      new Option({ short: '-s', description: 'Do not echo (terminal only).' }),
      new Option({ short: '-e', description: 'Use readline (terminal only).' }),
      new Option({ short: '-i', type: 'str', description: 'Initial text (terminal only).' }),
      new Option({ short: '-u', type: 'str', description: 'Read from this descriptor.' }),
    ],
    rest: new Operand({ type: 'str' }),
  }),
  mapfile: new CommandSpec({
    description: 'Read lines from standard input into an array.',
    options: [
      new Option({ short: '-d', type: 'str', description: 'Line delimiter instead of newline.' }),
      new Option({ short: '-n', type: 'str', description: 'Copy at most N lines.' }),
      new Option({ short: '-O', type: 'str', description: 'Start storing at this index.' }),
      new Option({ short: '-s', type: 'str', description: 'Discard the first N lines.' }),
      new Option({ short: '-t', description: 'Strip the delimiter.' }),
      new Option({ short: '-u', type: 'str', description: 'Read from this descriptor.' }),
      new Option({ short: '-C', type: 'str', description: 'Call this every quantum lines.' }),
      new Option({ short: '-c', type: 'str', description: 'Lines between callback calls.' }),
    ],
    rest: new Operand({ type: 'str' }),
  }),
})

/**
 * Result of a strict leading-option scan for a shell builtin.
 *
 * Wrapper builtins (xargs, timeout) stop option parsing at the first
 * operand, since everything after it belongs to the wrapped command;
 * the mount-command parser scans the whole line and warns-ignores
 * unknown flags, which is wrong on both counts here. The builtin owns
 * the error message and exit code (GNU shapes differ per tool), so
 * the parse only reports what went wrong. An optional-value option given
 * bare is `true` in `flags`; `given` lists every option in the order it
 * was given, for a builtin whose options act in turn (xargs -I, -L and
 * -n cancel one another). `needsValue` is the short char, or the long
 * token with its dashes.
 */
export interface ShellParse {
  flags: Record<string, string | boolean>
  given: [string, string | boolean][]
  operands: string[]
  invalid: string | null
  needsValue: string | null
}

/**
 * Scan leading options the way getopt does for a shell builtin.
 *
 * An optional-value option takes its value only when attached (`-iR`,
 * `--replace=R`), as getopt's `::` does.
 */
export function parseShellOptions(spec: CommandSpec, argv: readonly string[]): ShellParse {
  const shortBool = new Set<string>()
  const shortValue = new Set<string>()
  const shortOptional = new Set<string>()
  const longBool = new Set<string>()
  const longValue = new Set<string>()
  const longOptional = new Set<string>()
  const alias = new Map<string, string>()
  for (const opt of spec.options) {
    const short = opt.short === null ? null : opt.short.replace(/^-+/, '')
    const long = opt.long === null ? null : opt.long.replace(/^-+/, '')
    const name = short ?? long ?? ''
    if (short !== null) {
      ;(opt.type === 'bool' ? shortBool : opt.valueOptional ? shortOptional : shortValue).add(short)
      alias.set(short, name)
    }
    if (long !== null) {
      ;(opt.type === 'bool' ? longBool : opt.valueOptional ? longOptional : longValue).add(long)
      alias.set(long, name)
    }
  }
  const flags: Record<string, string | boolean> = {}
  const given: [string, string | boolean][] = []
  const record = (key: string, value: string | boolean): void => {
    flags[key] = value
    given.push([key, value])
  }
  let i = 0
  while (i < argv.length) {
    const tok = argv[i]
    if (tok === undefined) break
    if (tok === '--') {
      i += 1
      break
    }
    if (tok.startsWith('--') && tok.length > 2) {
      const eq = tok.indexOf('=')
      const name = eq >= 0 ? tok.slice(2, eq) : tok.slice(2)
      if (longBool.has(name)) {
        record(alias.get(name) ?? name, true)
      } else if (longOptional.has(name)) {
        record(alias.get(name) ?? name, eq >= 0 ? tok.slice(eq + 1) : true)
      } else if (longValue.has(name)) {
        if (eq >= 0) {
          record(alias.get(name) ?? name, tok.slice(eq + 1))
        } else {
          const value = argv[i + 1]
          if (value === undefined) {
            return {
              flags,
              given,
              operands: argv.slice(i + 1),
              invalid: null,
              needsValue: `--${name}`,
            }
          }
          i += 1
          record(alias.get(name) ?? name, value)
        }
      } else {
        return { flags, given, operands: argv.slice(i + 1), invalid: tok, needsValue: null }
      }
      i += 1
      continue
    }
    if (tok.startsWith('-') && tok.length > 1) {
      const chars = tok.slice(1)
      let j = 0
      while (j < chars.length) {
        const ch = chars[j]
        if (ch === undefined) break
        if (shortBool.has(ch)) {
          record(alias.get(ch) ?? ch, true)
          j += 1
          continue
        }
        if (shortOptional.has(ch)) {
          const attached = chars.slice(j + 1)
          record(alias.get(ch) ?? ch, attached === '' ? true : attached)
          break
        }
        if (shortValue.has(ch)) {
          const rest = chars.slice(j + 1)
          if (rest !== '') {
            record(alias.get(ch) ?? ch, rest)
          } else {
            const value = argv[i + 1]
            if (value === undefined) {
              return { flags, given, operands: argv.slice(i + 1), invalid: null, needsValue: ch }
            }
            i += 1
            record(alias.get(ch) ?? ch, value)
          }
          break
        }
        return { flags, given, operands: argv.slice(i + 1), invalid: ch, needsValue: null }
      }
      i += 1
      continue
    }
    break
  }
  return { flags, given, operands: argv.slice(i), invalid: null, needsValue: null }
}
