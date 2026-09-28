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

import { IOResult } from '../../../../io/types.ts'
import {
  errorVirtualPath,
  fsStrerror,
  isFsError,
  operandSpelling,
} from '../../../../utils/errors.ts'
import { DEFAULT_DIR_MODE, parseChmod } from '../../../../utils/mode.ts'
import { DEFAULT_UMASK, sessionUmask, walkProbeFor } from '../../../../context/session_context.ts'
import { specOf } from '../../../spec/builtins.ts'
import { FlagView } from '../../../spec/flag_view.ts'
import { mkdirLinkRefusal } from '../../utils/slash_links.ts'
import { descendantPath, entryKind } from '../../utils/paths.ts'
import type { Accessor } from '../../../../accessor/base.ts'
import type { LinkView } from '../../../../ops/types.ts'
import { FileType, PathSpec } from '../../../../types.ts'
import { mountPrefixOf } from '../../../../utils/key_prefix.ts'
import { resolvePath, walkNodes } from '../../../../utils/path.ts'
import { rstripSlash } from '../../../../utils/slash.ts'
import type { MkdirOp } from '../../../../vfs/types.ts'
import { type Builder, requireOp, resolveGlobOf } from '../adapter.ts'

/**
 * Make one name of a walk a directory, or say why it is not one.
 *
 * Judged the way GNU's walk into the name is, before anything is made: a
 * directory, or a link to one, is passed through; a plain file, or a link to
 * one, is ENOTDIR; a dangling link is EEXIST. Only a missing name is made,
 * where its links lead, so no store is asked to make a directory over a file
 * or under a link it cannot see. Outside a workspace command there is no stat
 * to judge with, and the store's own mkdir answers. Mirrors Python's
 * _enter_node.
 */
async function enterNode<A extends Accessor>(
  mkdir: MkdirOp<A>,
  accessor: A,
  path: PathSpec,
  node: string,
  root: string,
  links: LinkView | null,
): Promise<string | null> {
  if (links !== null && links.statAt(node) !== null) {
    const target = await links.targetStat(node)
    if (target === null) return 'File exists'
    return target.type === FileType.DIRECTORY ? null : 'Not a directory'
  }
  const probe = walkProbeFor(path.virtual)
  if (probe !== null) {
    const { exists, isDir } = await entryKind(probe.stat, PathSpec.fromStrPath(node))
    if (exists) return isDir ? null : 'Not a directory'
  }
  const real = links !== null ? links.resolve(node) : node
  if (real.startsWith(`${root}/`)) await mkdir(accessor, descendantPath(path, real), true)
  return null
}

/**
 * Make every name an operand's walk enters, GNU `mkdir -p` style.
 *
 * The backend's `parents` makes the ancestors of the simplified path, which
 * skips a name the walk passes through on its way to a `..`: GNU creates
 * `nope` for `mkdir -p nope/../m`. The operand itself is left to the caller;
 * a name in the way is quoted as the operand spells it. Null when every name
 * is made. Mirrors Python's _make_walked.
 */
async function makeWalked<A extends Accessor>(
  mkdir: MkdirOp<A>,
  accessor: A,
  path: PathSpec,
  dotted: string,
  links: LinkView | null,
): Promise<string | null> {
  const root = rstripSlash(mountPrefixOf(path.virtual, path.vfsPath))
  const final = resolvePath(dotted, '/')
  for (const [node, spelled] of walkNodes(dotted, path.rawPath)) {
    if (node === final) continue
    let why: string | null
    try {
      why = await enterNode(mkdir, accessor, path, node, root, links)
    } catch (err) {
      if (!isFsError(err)) throw err
      why =
        (err as { code?: string }).code === 'EEXIST' ? 'Not a directory' : String(fsStrerror(err))
    }
    if (why !== null) return `mkdir: cannot create directory '${spelled}': ${why}`
  }
  return null
}

/**
 * Make one mkdir operand, or the line GNU reports when it cannot.
 *
 * One unusable operand is not an aborted command: GNU reports it and still
 * makes the remaining directories. The error names the path to quote:
 * usually the operand, but `mkdir -p` blames the component of the chain it
 * tripped on. Every mkdir makes its operands here, a keyed store's override
 * included, so they report alike. Mirrors Python's make_directory.
 */
export async function makeDirectory<A extends Accessor>(
  mkdir: MkdirOp<A>,
  accessor: A,
  path: PathSpec,
  parents: boolean,
  links: LinkView | null = null,
): Promise<string | null> {
  let target = path
  if (parents && path.dotted !== null) {
    const failed = await makeWalked(mkdir, accessor, path, path.dotted, links)
    if (failed !== null) return failed
    // The walk has entered every name the spelling passes through, so the
    // operand is made by its resolved path alone: walking it again would ask
    // a store that shows no empty directory (hf) for one the walk just made.
    target = new PathSpec({
      virtual: path.virtual,
      directory: path.directory,
      vfsPath: path.vfsPath,
      pattern: path.pattern,
      resolved: path.resolved,
      rawPath: path.rawPath,
    })
  }
  try {
    await mkdir(accessor, target, parents)
  } catch (err) {
    if (!isFsError(err)) throw err
    const named = operandSpelling(errorVirtualPath(err), path)
    return `mkdir: cannot create directory '${named}': ${String(fsStrerror(err))}`
  }
  return null
}

export const MKDIR_BUILDER: Builder = {
  name: 'mkdir',
  write: true,
  fn: async (ops, accessor, paths, _texts, opts) => {
    const fl = new FlagView(opts.flags, specOf('mkdir'))
    const parents = fl.asBool('parents')
    const verbose = fl.asBool('verbose')
    const modeText = fl.asStr('mode') ?? null
    if (paths.length === 0) {
      return [
        null,
        new IOResult({
          exitCode: 1,
          stderr: new TextEncoder().encode('mkdir: missing operand\n'),
        }),
      ]
    }
    const idx = opts.index ?? undefined
    const { setAttrs } = ops
    const mkdir = requireOp(ops.mkdir, 'mkdir')
    let mode: number | null = null
    if (modeText !== null) {
      // Symbolic clauses build on what mirage renders for a new
      // directory; `-m` is applied after the create, so the session's
      // umask does not reach it, which is GNU's rule too.
      mode = parseChmod(modeText, DEFAULT_DIR_MODE)
      if (mode === null) throw new Error(`mkdir: invalid mode '${modeText}'`)
      if (setAttrs === undefined) {
        throw new Error('mkdir: --mode is not supported on this backend')
      }
    } else if (setAttrs !== undefined) {
      // A new directory is 0777 masked by the session's umask. Only a
      // mask away from bash's default costs a setattr, since 755 is what
      // every backend already renders for a fresh directory; parents
      // made by `-p` keep that default.
      const umask = sessionUmask()
      if (umask !== DEFAULT_UMASK) mode = 0o777 & ~umask
    }
    const resolved = await resolveGlobOf(ops)(accessor, paths, idx)
    const lines: string[] = []
    const errors: string[] = []
    const links = opts.ns?.links ?? null
    for (const p of resolved) {
      const collision = await mkdirLinkRefusal(p, links, { parents })
      if (collision.taken) {
        if (collision.message !== null) errors.push(collision.message)
        continue
      }
      const failed = await makeDirectory(mkdir, accessor, p, parents, links)
      if (failed !== null) {
        errors.push(failed)
        continue
      }
      // -m applies to the named directory only; any parents made by -p keep
      // the default mode (GNU).
      if (mode !== null && setAttrs !== undefined) await setAttrs(accessor, p, { mode })
      if (verbose) lines.push(`mkdir: created directory '${p.virtual}'`)
    }
    const out = lines.length > 0 ? new TextEncoder().encode(lines.join('\n') + '\n') : null
    const stderr = errors.length > 0 ? new TextEncoder().encode(errors.join('\n') + '\n') : null
    return [out, new IOResult({ stderr, exitCode: errors.length > 0 ? 1 : 0 })]
  },
}
