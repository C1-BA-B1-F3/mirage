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

import { classify } from '../../../errors/index.ts'
import { normDir } from '../../../utils/slash.ts'
import { DIR_MODE } from '../../../utils/stat_view.ts'
import { parseMode } from '../../handles/mode.ts'
import { applyOpen } from '../../open.ts'
import type { RuntimeVFS } from '../../vfs.ts'
import type { MontyBindingBits } from './binding.ts'
import { MAX_URANDOM_BYTES, NOT_A_LINK } from './constants.ts'
import { asGuestError, guestError } from './errors.ts'
import { mergeEntries } from './list.ts'
import { isDirRow, isRegularRow, statResult } from './stat.ts'
import { ScratchTree } from './tree.ts'

function pathArg(value: unknown): string | null {
  if (typeof value === 'string') return value
  if (value !== null && typeof value === 'object' && 'path' in value) {
    const p = (value as { path: unknown }).path
    return typeof p === 'string' ? p : null
  }
  return null
}

/** Character count the way python's `len` counts: code points, not UTF-16 units. */
function textLength(data: unknown): number {
  return Array.from(String(data)).length
}

function payloadBytes(data: unknown): Uint8Array {
  if (data instanceof Uint8Array) return data
  return new TextEncoder().encode(typeof data === 'string' ? data : '')
}

/** Match Python OSAccess's per-call entropy cap before allocating host memory. */
function urandom(value: unknown): Uint8Array {
  const size = Number(value)
  if (size > MAX_URANDOM_BYTES) {
    throw Object.assign(
      new Error(`os.urandom() size exceeds max_urandom_bytes (${String(MAX_URANDOM_BYTES)})`),
      { name: 'MemoryError' },
    )
  }
  if (!Number.isSafeInteger(size) || size < 0) throw new TypeError('invalid os.urandom size')
  const bytes = new Uint8Array(size)
  // Web Crypto accepts at most 64 KiB per call, including in Node.
  for (let offset = 0; offset < size; offset += 65_536) {
    globalThis.crypto.getRandomValues(bytes.subarray(offset, Math.min(offset + 65_536, size)))
  }
  return bytes
}

interface TimeZoneMarker {
  offsetSeconds: number
  name?: string
}

function timeZoneArg(value: unknown): TimeZoneMarker | null {
  if (value === null || typeof value !== 'object') return null
  const marker = value as { __monty_type__?: unknown; offsetSeconds?: unknown; name?: unknown }
  if (marker.__monty_type__ !== 'TimeZone' || typeof marker.offsetSeconds !== 'number') return null
  return {
    offsetSeconds: marker.offsetSeconds,
    ...(typeof marker.name === 'string' ? { name: marker.name } : {}),
  }
}

/**
 * The host clock as monty's DateTime marker, which the binding turns
 * into a real guest `datetime`. No timezone argument means python's
 * naive local now; a TimeZone marker means an aware now in that
 * offset — both exactly what the python binding's default
 * `datetime_now(tz)` answers.
 */
function dateTimeMarker(tz: TimeZoneMarker | null): Record<string, unknown> {
  if (tz === null) {
    const now = new Date()
    return {
      __monty_type__: 'DateTime',
      year: now.getFullYear(),
      month: now.getMonth() + 1,
      day: now.getDate(),
      hour: now.getHours(),
      minute: now.getMinutes(),
      second: now.getSeconds(),
      microsecond: now.getMilliseconds() * 1000,
    }
  }
  const shifted = new Date(Date.now() + tz.offsetSeconds * 1000)
  return {
    __monty_type__: 'DateTime',
    year: shifted.getUTCFullYear(),
    month: shifted.getUTCMonth() + 1,
    day: shifted.getUTCDate(),
    hour: shifted.getUTCHours(),
    minute: shifted.getUTCMinutes(),
    second: shifted.getUTCSeconds(),
    microsecond: shifted.getUTCMilliseconds() * 1000,
    offsetSeconds: tz.offsetSeconds,
    ...(tz.name !== undefined ? { timezoneName: tz.name } : {}),
  }
}

function dateMarker(): Record<string, unknown> {
  const now = new Date()
  return {
    __monty_type__: 'Date',
    year: now.getFullYear(),
    month: now.getMonth() + 1,
    day: now.getDate(),
  }
}

/** The parent directory of an absolute guest path. */
function parentOf(path: string): string {
  const slash = path.replace(/\/+$/, '').lastIndexOf('/')
  return slash <= 0 ? '/' : path.slice(0, slash)
}

/**
 * Monty's OS door: a mounted path is the workspace's, any other scratch.
 *
 * This is monty's tier of the interception taxonomy: the binding calls
 * one host callback per operation and takes back a value (or a promise
 * of one) or NOT_HANDLED, which the sandbox raises as the call's
 * default refusal. Every call routes on the path. One a mount serves is
 * answered by the file door alone, with the mount's own rows and
 * CPython's wording for its refusals; any other path is guest scratch
 * space, served by a per-run `ScratchTree`, so `/tmp` really does
 * behave like `/tmp`. The python twin routes the same way over the
 * binding's own in-memory tree. Declining is reserved for what neither
 * half can serve: an operation this door does not implement.
 *
 * Monty hands the door whole-file calls: an open, then reads of the
 * whole file and appends of each new write. So an open applies its
 * mode's effect on the mount (`applyOpen`) and nothing else, and
 * each write after it ships only its own bytes.
 *
 * Args:
 *   binding: the loaded binding's door pieces (NOT_HANDLED sentinel
 *     and the MontyFileHandle an `open` answer must be).
 *   env: the run's environment, readable both ways python's monty
 *     spells it (`os.getenv` and `os.environ`).
 *   door: the execution's file door, or null when no workspace is
 *     attached.
 */
export class MirageOSAccess {
  private readonly bits: MontyBindingBits
  private readonly notHandled: symbol
  private readonly fileHandle: MontyBindingBits['MontyFileHandle']
  private readonly env: Record<string, string>
  private readonly door: RuntimeVFS | null
  private readonly tree = new ScratchTree()

  constructor(binding: MontyBindingBits, env: Record<string, string>, door: RuntimeVFS | null) {
    this.bits = binding
    this.notHandled = binding.NOT_HANDLED
    this.fileHandle = binding.MontyFileHandle
    this.env = env
    this.door = door
  }

  readonly handle = (
    name: string,
    args: unknown[],
    kwargs: Record<string, unknown> = {},
  ): unknown => {
    if (name === 'os.getenv') {
      // hasOwn, not `in`: the guest picks the key, so a name like
      // `toString` must miss instead of leaking a host function.
      const key = String(args[0])
      if (Object.hasOwn(this.env, key)) return this.env[key]
      return args.length > 1 ? args[1] : null
    }
    if (name === 'os.environ') {
      // The engine asks for the whole mapping as one call; a plain
      // object arrives in the guest as a dict, so `.get`, `[...]`,
      // `in`, iteration and len all work, and a missing key raises
      // KeyError. A copy, like python's OSAccess(environ=dict(environ)):
      // a guest that mutates it cannot reach the session's own env.
      return { ...this.env }
    }
    // The clock doors: python's binding defaults these to the host
    // clock, so declining them (a guest RuntimeError) was a divergence
    // for any program that stamps its output.
    if (name === 'datetime.now') return dateTimeMarker(timeZoneArg(args[0]))
    if (name === 'date.today') return dateMarker()
    if (name === 'os.urandom') return urandom(args[0])
    // Everything below serves a path; the doors above need none.
    const path = pathArg(args[0])
    if (path === null) return this.notHandled
    // Lexical questions need no mount and no tree entry: monty's own
    // tree resolves no symlinks, so resolve() is absolute() and '/' is
    // the working directory, which is also what python's binding
    // answers (a str, on both hosts).
    if (name === 'Path.resolve' || name === 'Path.absolute') {
      return path.startsWith('/') ? path : '/' + path
    }
    const door = this.door
    const out =
      door?.serves(path) === true
        ? this.mountedOp(name, path, args, kwargs, door)
        : this.scratchOp(name, path, args, kwargs)
    if (!(out instanceof Promise)) return out
    // A mount words its refusals its own way; the guest catches the
    // builtin CPython raises and may print its message. The tree's own
    // errors are already that shape and pass through.
    const target = name === 'Path.rename' ? (pathArg(args[1]) ?? undefined) : undefined
    return out.catch((caught: unknown) => {
      throw asGuestError(caught, path, target)
    })
  }

  /** A path some mount serves: every answer is the workspace's. */
  private mountedOp(
    name: string,
    path: string,
    args: unknown[],
    kwargs: Record<string, unknown>,
    door: RuntimeVFS,
  ): unknown {
    switch (name) {
      case 'open':
        return this.openMounted(path, typeof args[1] === 'string' ? args[1] : 'r', door)
      case 'Path.read_bytes':
        return door.read(path)
      case 'Path.read_text':
        return door.read(path).then((b) => new TextDecoder().decode(b))
      case 'Path.write_bytes':
      case 'Path.write_text':
        return this.writeMounted(path, args[1], door)
      case 'Path.append_bytes':
      case 'Path.append_text':
        return this.appendMounted(path, args[1], door)
      case 'Path.mkdir':
        return this.mkdirMounted(path, kwargs, door)
      case 'Path.rmdir':
        return door.rmdir(path).then(() => null)
      case 'Path.unlink':
        return door.unlink(path).then(() => null)
      case 'Path.rename': {
        const dst = pathArg(args[1])
        if (dst === null) return this.notHandled
        // A destination outside the workspace crosses out of the
        // mount world; EXDEV is what POSIX answers for a rename
        // across filesystems and what python raises here.
        if (!door.serves(dst)) throw guestError('EXDEV', path, dst)
        return door.rename(path, dst).then(() => null)
      }
      case 'Path.iterdir':
        return door.readdir(normDir(path), false).then((entries) =>
          mergeEntries(
            path,
            [],
            entries.map((e) => e.path),
          ),
        )
      // The mount's own row answers the predicates whenever it has
      // one. The listing stays for the one path with no row of its
      // own, a directory the mount only implies.
      case 'Path.is_dir':
        return door
          .statOrNull(path)
          .then((st) => (st !== null ? isDirRow(st) : this.listable(path)))
      case 'Path.is_symlink':
        return this.isLink(path)
      case 'Path.is_file':
        return door.statOrNull(path).then((st) => st !== null && isRegularRow(st))
      case 'Path.exists':
        return door.statOrNull(path).then((st) => st !== null || this.listable(path))
      case 'Path.stat':
        return door
          .statOrNull(path)
          .then((st) => (st === null ? this.scratchStat(path) : statResult(this.bits, st)))
      default:
        return this.notHandled
    }
  }

  /** A path no mount serves: the guest's scratch space, answered from the tree. */
  private scratchOp(
    name: string,
    path: string,
    args: unknown[],
    kwargs: Record<string, unknown>,
  ): unknown {
    switch (name) {
      case 'open': {
        const mode = typeof args[1] === 'string' ? args[1] : 'r'
        const handle = new this.fileHandle(path, mode)
        const facts = parseMode(mode)
        const open = (): unknown => {
          this.tree.open(path, facts)
          return handle
        }
        return facts.writable ? this.creating(path, open) : open()
      }
      case 'Path.read_text':
        return this.tree.readText(path)
      case 'Path.read_bytes':
        return this.tree.readBytes(path)
      case 'Path.write_text':
        return this.creating(path, () => {
          this.tree.write(path, String(args[1]))
          return textLength(args[1])
        })
      case 'Path.write_bytes': {
        const data = payloadBytes(args[1])
        return this.creating(path, () => {
          this.tree.write(path, data)
          return data.length
        })
      }
      case 'Path.append_text':
        return this.creating(path, () => {
          this.tree.append(path, String(args[1]))
          return textLength(args[1])
        })
      case 'Path.append_bytes': {
        const data = payloadBytes(args[1])
        return this.creating(path, () => {
          this.tree.append(path, data)
          return data.length
        })
      }
      case 'Path.mkdir':
        return this.creating(path, () => {
          this.tree.mkdir(path, kwargs.parents === true, kwargs.exist_ok === true)
          return null
        })
      case 'Path.unlink':
        this.tree.unlink(path)
        return null
      case 'Path.rmdir':
        this.tree.rmdir(path)
        return null
      case 'Path.rename': {
        const dst = pathArg(args[1])
        if (dst === null) return this.notHandled
        // Crossing into a mount is the same filesystem boundary as
        // crossing out of one.
        if (this.door?.serves(dst) === true) throw guestError('EXDEV', path, dst)
        return this.creating(dst, () => {
          this.tree.rename(path, dst)
          return null
        })
      }
      case 'Path.exists':
      case 'Path.is_dir':
        if (name === 'Path.exists' ? this.tree.exists(path) : this.tree.isDir(path)) return true
        return this.listable(path)
      case 'Path.is_file':
        return this.tree.isFile(path)
      case 'Path.is_symlink':
        // The tree holds no links, but the name plane may hold one at
        // an unmounted path; python asks the workspace the same way.
        return this.isLink(path)
      case 'Path.iterdir':
        return this.scratchIterdir(path)
      case 'Path.stat':
        return this.scratchStat(path)
      default:
        return this.notHandled
    }
  }

  /**
   * Run a scratch create once its parent is a tree directory, making it
   * one when only the workspace has it. A directory the workspace lists
   * but no mount claims (the root above nested mounts) is one the guest
   * sees as a directory, so a scratch file may be created in it like in
   * any other; the tree holds it from then on, and its listing merges
   * both.
   */
  private creating(path: string, run: () => unknown): unknown {
    const parent = parentOf(path)
    if (this.tree.exists(parent)) return run()
    const listed = this.listable(parent)
    if (listed === false) return run()
    return Promise.resolve(listed).then((found) => {
      if (found) this.tree.mkdir(parent, true, true)
      return run()
    })
  }

  /**
   * Whether the workspace lists `path`, served or not: the root above
   * nested mounts, `/parent` when only `/parent/child` is mounted, and
   * a directory a mount lists but has no row for.
   */
  private listable(path: string): boolean | Promise<boolean> {
    if (this.door === null) return false
    return this.door.listingOrNull(path).then((entries) => entries !== null)
  }

  /**
   * Whether the name plane holds a symlink at `path`, asked through
   * readlink on either route: the tree holds no links, and the name
   * plane may hold one at an unmounted path. A refusal the backend did
   * not mean as "no link here" comes out as itself (NOT_A_LINK), which
   * is what CPython's own `Path.is_symlink` does.
   */
  private isLink(path: string): boolean | Promise<boolean> {
    if (this.door === null) return false
    return this.door.readlink(path).then(
      () => true,
      (caught: unknown) => {
        const condition = classify(caught)
        if (condition === null || !NOT_A_LINK.has(condition)) throw caught
        return false
      },
    )
  }

  /**
   * The scratch tree's row for `path`, as the guest's `os.stat_result`.
   * A directory the workspace lists but has no row for is not in the
   * tree, and stats as monty's default directory, what python's
   * `StatResult.dir_stat()` answers.
   */
  private scratchStat(path: string): unknown {
    if (this.tree.exists(path)) return statResult(this.bits, this.tree.stat(path))
    return Promise.resolve(this.listable(path)).then((listed) =>
      statResult(
        this.bits,
        listed
          ? { size: 0, isDir: true, mtimeMs: Date.now(), mode: DIR_MODE }
          : this.tree.stat(path),
      ),
    )
  }

  /**
   * List a scratch directory, folding in whatever the workspace lists
   * under the same name: `iterdir('/')` must show the mount roots
   * beside the guest's own scratch entries. A path neither side can
   * list raises the tree's own FileNotFoundError.
   */
  private scratchIterdir(path: string): unknown {
    if (this.door === null) return this.tree.iterdir(path)
    return this.door.listingOrNull(path).then((entries) => {
      if (entries === null) return this.tree.iterdir(path)
      return mergeEntries(
        path,
        this.tree.isDir(path) ? this.tree.iterdir(path) : [],
        entries.map((entry) => entry.path),
      )
    })
  }

  private async openMounted(path: string, mode: string, door: RuntimeVFS): Promise<unknown> {
    // Handle first, mirroring monty's own tree: a malformed mode must
    // raise before any side effect lands on the mount.
    const handle = new this.fileHandle(path, mode)
    await applyOpen(door, path, parseMode(mode))
    return handle
  }

  /** Replace a mounted file; the return is python's: characters for text, bytes for bytes. */
  private async writeMounted(path: string, data: unknown, door: RuntimeVFS): Promise<number> {
    const bytes = payloadBytes(data)
    await door.write(path, bytes)
    return typeof data === 'string' ? textLength(data) : bytes.length
  }

  /**
   * Send only the appended bytes; monty hands an append nothing else.
   * Re-sending everything written so far turns a write loop quadratic,
   * so a mount with its own append op carries just these bytes, and the
   * door falls back to a whole-file write only for the mount without
   * one. The return is python's: characters for text, bytes for bytes.
   */
  private async appendMounted(path: string, data: unknown, door: RuntimeVFS): Promise<number> {
    const tail = payloadBytes(data)
    await door.append(path, tail)
    return typeof data === 'string' ? textLength(data) : tail.length
  }

  /**
   * Create a mounted directory, keeping pathlib's flags: `parents`
   * rides through to the backend op, which takes it; `exist_ok` is
   * answered here, since the op has no such argument and backends
   * differ on whether creating an existing directory raises at all.
   * `exist_ok` forgives an existing directory only — a file at the
   * target still raises, pathlib's own rule.
   */
  private async mkdirMounted(
    path: string,
    kwargs: Record<string, unknown>,
    door: RuntimeVFS,
  ): Promise<null> {
    const row = await door.statOrNull(path)
    if (row !== null && !isDirRow(row)) throw guestError('EEXIST', path)
    if (row !== null || (await this.listable(path))) {
      if (kwargs.exist_ok === true) return null
      throw guestError('EEXIST', path)
    }
    await door.mkdir(path, kwargs.parents === true)
    return null
  }
}
