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

import { compileSpec } from '../spec/compile.ts'
import type { CLISpec } from './types.ts'

/**
 * Validate one CLISpec node at construction time.
 *
 * Called from the CLISpec constructor, so an invalid node throws at import
 * time, never at dispatch. Children were validated by their own
 * construction (a nested literal builds bottom up), so each call checks one
 * level: the name is a single word with no whitespace, a node takes exactly
 * one of fn, subcommands, or script (a script root stands alone and takes
 * opaque config: the program re-parses argv natively), runtime only rides a
 * script, every node's inherited CommandSpec grammar compiles, a group
 * declares no positional/rest (its operand is the subcommand word), child
 * names are unique, and only a tree's root may declare configModel or
 * script.
 *
 * Args:
 *   node: the freshly constructed node.
 */
export function validateCli(node: CLISpec): void {
  if (node.name === '' || /\s/.test(node.name)) {
    throw new Error(`cli name '${node.name}' must be a single non-empty word`)
  }
  for (const alias of node.aliases) {
    if (alias === '' || /\s/.test(alias)) {
      throw new Error(`cli '${node.name}': alias '${alias}' must be a single non-empty word`)
    }
  }
  if (node.script !== null && node.fn !== null) {
    throw new Error(`cli '${node.name}': a node takes fn or script, not both`)
  }
  if (node.script !== null && node.subcommands.length > 0) {
    throw new Error(
      `cli '${node.name}': a script serves the whole program; subcommands belong to fn trees`,
    )
  }
  if (node.script !== null && node.configModel !== null) {
    throw new Error(`cli '${node.name}': script config is opaque; it cannot declare configModel`)
  }
  if (node.runtime !== null && node.script === null) {
    throw new Error(`cli '${node.name}': runtime names the entry that runs script; it takes script`)
  }
  if (node.fn !== null && node.subcommands.length > 0) {
    throw new Error(`cli '${node.name}': a node takes fn or subcommands, not both`)
  }
  if (node.fn === null && node.subcommands.length === 0 && node.script === null) {
    throw new Error(`cli '${node.name}': a node needs fn, subcommands, or script`)
  }
  if (node.subcommands.length > 0 && (node.positional.length > 0 || node.rest !== null)) {
    throw new Error(
      `cli '${node.name}': a group's operand is its subcommand word; ` +
        'positional/rest belong on leaves',
    )
  }
  const compiled = compileSpec(node)
  // Names and aliases share one sibling namespace (argparse refuses a
  // conflicting subparser alias the same way).
  const seen = new Set<string>()
  for (const child of node.subcommands) {
    for (const word of [child.name, ...child.aliases]) {
      if (seen.has(word)) {
        throw new Error(`cli '${node.name}': duplicate subcommand '${word}'`)
      }
      seen.add(word)
    }
    if (child.configModel !== null) {
      throw new Error(
        `cli '${node.name}': subcommand '${child.name}' declares configModel; ` +
          'only the root of a tree may',
      )
    }
    if (child.script !== null) {
      throw new Error(
        `cli '${node.name}': subcommand '${child.name}' declares script; ` +
          'only the root of a tree may',
      )
    }
  }
  if (node.options.length > 0 && node.subcommands.length > 0) {
    const own = new Set(compiled.dest.values())
    for (const child of node.subcommands) {
      checkCollisions(node.name, own, child, [child.name])
    }
  }
}

/**
 * Refuse an option spelled the same on a node and any descendant. The walk
 * consumes group options level by level into one flag bag, so an
 * ancestor/descendant collision would be ambiguous there; siblings may
 * freely share spellings. Children validated themselves already, so this
 * only compares each descendant against the ancestor set.
 */
function checkCollisions(
  rootName: string,
  ancestorDests: ReadonlySet<string>,
  node: CLISpec,
  path: readonly string[],
): void {
  if (node.options.length > 0) {
    for (const dest of compileSpec(node).dest.values()) {
      if (ancestorDests.has(dest)) {
        throw new Error(
          `cli '${rootName}': option '${dest}' collides with subcommand '${path.join(' ')}'`,
        )
      }
    }
  }
  for (const child of node.subcommands) {
    checkCollisions(rootName, ancestorDests, child, [...path, child.name])
  }
}
