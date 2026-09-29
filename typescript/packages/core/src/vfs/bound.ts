import type { Accessor } from '../accessor/base.ts'
import type { IndexCacheStore } from '../cache/index/store.ts'
import { resolveGlobOf, type CommandIO } from '../commands/builtin/generic_bind/adapter.ts'
import { PathSpec, type FileStat } from '../types.ts'
import { mountKey, mountPrefixOf } from '../utils/key_prefix.ts'
import { BaseVFS, type FindOptions } from './base.ts'
import { VFSAdapter } from './adapter.ts'

/** Shared binding for builtin and custom VFS; lifecycle belongs to the subclass. */

export abstract class BoundVFS<A extends Accessor = Accessor> extends BaseVFS {
  declare writeFile?: (path: PathSpec, data: Uint8Array) => Promise<void>

  declare appendFile?: (path: PathSpec, data: Uint8Array) => Promise<void>

  declare exists?: (path: PathSpec) => Promise<boolean>

  declare mkdir?: (path: PathSpec, options?: { recursive?: boolean }) => Promise<void>

  declare rmdir?: (path: PathSpec) => Promise<void>

  declare unlink?: (path: PathSpec) => Promise<void>

  declare rename?: (src: PathSpec, dst: PathSpec) => Promise<void>

  declare truncate?: (path: PathSpec, length: number) => Promise<void>

  declare copy?: (src: PathSpec, dst: PathSpec) => Promise<void>

  declare rmR?: (path: PathSpec) => Promise<void>

  declare du?: (path: PathSpec) => Promise<number>

  declare find?: (path: PathSpec, options?: FindOptions) => Promise<string[]>

  abstract readonly accessor: A
  readonly io: CommandIO<A>

  constructor(table: CommandIO<A> | VFSAdapter<A>) {
    super()
    this.io = table instanceof VFSAdapter ? table.toCommandIO() : table
    this.#installOptional(this.io)
  }
  // Each forwarder reads `this.index` when called rather than capturing
  // it, because `setIndex` can replace it after construction.
  #installOptional(io: CommandIO<A>): void {
    const { write, append, exists, mkdir, rmdir, unlink } = io
    const { rename, truncate, copy, rmR, du, find } = io
    if (write !== undefined && this.writeFile === undefined)
      this.writeFile = (p, d) => write(this.accessor, p, d)
    if (append !== undefined && this.appendFile === undefined)
      this.appendFile = (p, d) => append(this.accessor, p, d)
    if (exists !== undefined && this.exists === undefined)
      this.exists = (p) => exists(this.accessor, p)
    if (mkdir !== undefined && this.mkdir === undefined)
      this.mkdir = (p, o) => mkdir(this.accessor, p, o?.recursive)
    if (rmdir !== undefined && this.rmdir === undefined) this.rmdir = (p) => rmdir(this.accessor, p)
    if (unlink !== undefined && this.unlink === undefined)
      this.unlink = (p) => unlink(this.accessor, p)
    if (rename !== undefined && this.rename === undefined)
      this.rename = (s, d) => rename(this.accessor, s, d)
    if (truncate !== undefined && this.truncate === undefined)
      this.truncate = (p, n) => truncate(this.accessor, p, n)
    if (copy !== undefined && this.copy === undefined)
      this.copy = (s, d) => copy(this.accessor, s, d)
    if (rmR !== undefined && this.rmR === undefined) this.rmR = (p) => rmR(this.accessor, p)
    if (du !== undefined && this.du === undefined)
      this.du = (p) => du.size(this.accessor, p, this.index)
    if (find !== undefined && this.find === undefined)
      this.find = (p, o) => find(this.accessor, p, o ?? {})
  }

  glob(paths: readonly PathSpec[], prefix = '', index?: IndexCacheStore): Promise<PathSpec[]> {
    const effective = prefix
      ? paths.map((p) =>
          mountPrefixOf(p.virtual, p.vfsPath)
            ? p
            : new PathSpec({
                virtual: p.virtual,
                directory: p.directory,
                ...(p.pattern !== null ? { pattern: p.pattern } : {}),
                resolved: p.resolved,
                vfsPath: mountKey(p.virtual, prefix),
              }),
        )
      : paths
    return resolveGlobOf(this.io)(this.accessor, effective, index ?? this.index)
  }
  readFile(path: PathSpec): Promise<Uint8Array> {
    return this.io.readBytes(this.accessor, path, this.index)
  }

  readdir(path: PathSpec): Promise<string[]> {
    return this.io.readdir(this.accessor, path, this.index)
  }

  stat(path: PathSpec, index?: IndexCacheStore): Promise<FileStat> {
    return this.io.stat(this.accessor, path, index ?? this.index)
  }

  streamPath(path: PathSpec): AsyncIterable<Uint8Array> {
    return this.io.readStream(this.accessor, path, this.index)
  }
}
