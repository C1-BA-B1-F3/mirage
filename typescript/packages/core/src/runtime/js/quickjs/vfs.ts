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

import { resolvePath } from '../../../utils/path.ts'
import { PathSpec } from '../../../types.ts'
import { isMissingPath } from '../../../utils/errors.ts'
import { WASI } from './wasi.ts'
import { wasiErrno } from './errors.ts'
import { readdir } from './list.ts'
import { stat } from './stat.ts'
import { epochToIso } from '../../../utils/dates.ts'
import { FileHandle, FileTable, parseMode, type OpenMode } from '../../handles/index.ts'
import type { RuntimeVFS, VFSStat } from '../../vfs.ts'
import type { QuickJSAsyncContext, QuickJSHandle } from 'quickjs-emscripten'

const ENC = new TextEncoder()
const DEC = new TextDecoder('utf-8', { fatal: false })

// WASI preview1 errnos this shim answers with directly. The numbering
// lives beside this shim (wasi.ts, the same numbers python's abi.py
// keeps): guests compare against these, so host errno numbering must
// not leak.
const ENOENT = WASI.ENOENT

/**
 * Install the `std.open`/`os.readdir` host functions on an asyncified
 * quickjs context, backed by the runtime vfs. A null vfs (no
 * workspace mounts wired) still installs the surface, but every open
 * and readdir fails cleanly — `std.open` returns null and `os.readdir`
 * reports ENOENT — so guest code sees an empty filesystem rather than a
 * missing global.
 *
 * @param ctx - the asyncified quickjs context
 * @param vfs - the runtime's mount vocabulary, or null when no mounts are wired
 */
export function installMirageFs(ctx: QuickJSAsyncContext, vfs: RuntimeVFS | null): void {
  const table = new FileTable<FileHandle>()
  let cwd = PathSpec.fromStrPath('/')
  const absolute = (handle: QuickJSHandle): string => {
    const path = ctx.getString(handle)
    return path === '' ? '' : resolvePath(path, cwd.virtual)
  }

  const mountOf = (path: string): string | null => (vfs === null ? null : vfs.mountOf(path))

  const underMount = (path: string): boolean => mountOf(path) !== null

  const defineAsync = (
    name: string,
    fn: (...args: QuickJSHandle[]) => Promise<QuickJSHandle>,
  ): void => {
    const handle = ctx.newAsyncifiedFunction(name, fn)
    ctx.setProp(ctx.global, name, handle)
    handle.dispose()
  }

  const defineSync = (name: string, fn: (...args: QuickJSHandle[]) => QuickJSHandle): void => {
    const handle = ctx.newFunction(name, fn)
    ctx.setProp(ctx.global, name, handle)
    handle.dispose()
  }

  defineSync('__mirage_getcwd', () => ctx.newString(cwd.virtual))

  defineAsync('__mirage_chdir', async (pathH) => {
    const path = absolute(pathH)
    if (path !== '/') {
      if (vfs === null || path === '') return ctx.newNumber(-ENOENT)
      try {
        if (!(await vfs.stat(path)).isDir) return ctx.newNumber(-WASI.ENOTDIR)
      } catch (err) {
        return ctx.newNumber(-wasiErrno(err))
      }
    }
    cwd = PathSpec.fromStrPath(path)
    return ctx.newNumber(0)
  })

  defineAsync('__mirage_open', async (pathH, modeH) => {
    const path = absolute(pathH)
    // The engine validates the mode before touching the filesystem
    // (qjs-libc throws TypeError before any open); -2 tells the
    // bootstrap to raise that refusal, since a host throw would not
    // arrive typed. The shared parser is stricter than qjs-libc's
    // character scan ('rr' passes strspn but not CPython's one-base
    // rule); the strict answer is the one both guests can agree on.
    let mode: OpenMode
    try {
      mode = parseMode(ctx.getString(modeH))
    } catch {
      return ctx.newNumber(-2)
    }
    if (vfs === null || !underMount(path)) return ctx.newNumber(-1)
    let st: VFSStat | null = null
    try {
      st = await vfs.stat(path)
    } catch (err) {
      // Only a confirmed absence reads as "no file yet" (the python
      // host's stat_or_none makes the same distinction): a transient
      // failure or a policy denial on an existing file must refuse the
      // open, or a create-capable mode would create over content this
      // open never saw.
      if (!isMissingPath(err)) return ctx.newNumber(-1)
    }
    // The same ladder as the python wasi host's path_open, so the two
    // engines refuse the same opens: a directory, an exclusive open
    // over an existing file (EEXIST in the real engine), and a missing
    // file whose mode does not create.
    if (st?.isDir === true) return ctx.newNumber(-1)
    if (st !== null && mode.exclusive) return ctx.newNumber(-1)
    if (st === null && !mode.create) return ctx.newNumber(-1)
    // The establishing op goes through the mount at open as the op it
    // is — create for a missing file, truncate for a discarded one —
    // so write modes and a read-narrowed session refuse here (the
    // guest gets null), the ledger records the real op, and a backend
    // with a native truncate receives it.
    let buf: Uint8Array = new Uint8Array()
    try {
      if (st === null) {
        await vfs.create(path)
      } else if (mode.truncate) {
        await vfs.truncate(path)
      } else {
        buf = await vfs.read(path)
      }
    } catch {
      return ctx.newNumber(-1)
    }
    const fd = table.add(FileHandle.opened(path, buf, mode))
    return ctx.newNumber(fd)
  })

  defineAsync('__mirage_close', async (fdH) => {
    const file = table.pop(ctx.getNumber(fdH))
    if (file === undefined) return ctx.undefined
    if (file.dirty && file.writable && vfs !== null) {
      await vfs.flush(file.path, file.baseLen, file.lowWrite, file.buf)
    }
    return ctx.undefined
  })

  defineAsync('__mirage_readdir', (pathH) => readdir(ctx, vfs, absolute(pathH)))

  defineSync('__mirage_read', (fdH, maxH) => {
    const file = table.get(ctx.getNumber(fdH))
    if (file === undefined) return ctx.newString('')
    return ctx.newString(DEC.decode(file.read(ctx.getNumber(maxH))))
  })

  defineSync('__mirage_getline', (fdH) => {
    const file = table.get(ctx.getNumber(fdH))
    if (file === undefined || file.pos >= file.buf.length) return ctx.null
    let end = file.pos
    while (end < file.buf.length && file.buf[end] !== 0x0a) end++
    const line = file.buf.subarray(file.pos, end)
    file.pos = end < file.buf.length ? end + 1 : end
    return ctx.newString(DEC.decode(line))
  })

  defineSync('__mirage_write', (fdH, textH) => {
    const file = table.get(ctx.getNumber(fdH))
    if (file?.writable) file.write(ENC.encode(ctx.getString(textH)))
    return ctx.undefined
  })

  defineSync('__mirage_seek', (fdH, offsetH, whenceH) => {
    const file = table.get(ctx.getNumber(fdH))
    if (file === undefined) return ctx.undefined
    const offset = ctx.getNumber(offsetH)
    const whence = ctx.getNumber(whenceH)
    const base = whence === 1 ? file.pos : whence === 2 ? file.buf.length : 0
    file.pos = Math.max(0, base + offset)
    return ctx.undefined
  })

  defineSync('__mirage_tell', (fdH) => {
    const file = table.get(ctx.getNumber(fdH))
    return ctx.newNumber(file === undefined ? -1 : file.pos)
  })

  defineSync('__mirage_eof', (fdH) => {
    const file = table.get(ctx.getNumber(fdH))
    const atEof = file === undefined || file.eof
    return atEof ? ctx.true : ctx.false
  })

  // The os.* mutation surface, matching the real engine's conventions
  // (pinned live against qjs-wasi through the python runtime): 0 on
  // success, -errno on failure in WASI numbering; os.remove takes
  // files and empty directories; os.stat answers [obj, errno].
  defineAsync('__mirage_remove', async (pathH) => {
    const path = absolute(pathH)
    if (vfs === null || !underMount(path)) return ctx.newNumber(-ENOENT)
    try {
      const st = await vfs.stat(path)
      if (st.isDir) {
        await vfs.rmdir(path)
      } else {
        await vfs.unlink(path)
      }
      return ctx.newNumber(0)
    } catch (err) {
      return ctx.newNumber(-wasiErrno(err))
    }
  })

  defineAsync('__mirage_mkdir', async (pathH) => {
    const path = absolute(pathH)
    if (vfs === null || !underMount(path)) return ctx.newNumber(-ENOENT)
    try {
      await vfs.mkdir(path)
      return ctx.newNumber(0)
    } catch (err) {
      return ctx.newNumber(-wasiErrno(err))
    }
  })

  defineAsync('__mirage_utimes', async (pathH, atimeH, mtimeH) => {
    const path = absolute(pathH)
    if (vfs === null || !underMount(path)) return ctx.newNumber(-ENOENT)
    // The engine's stamps are milliseconds (qjs-libc splits them into
    // tv_sec/tv_nsec at 1000), and the op takes ISO text.
    const atime = epochToIso(ctx.getNumber(atimeH) / 1000)
    const mtime = epochToIso(ctx.getNumber(mtimeH) / 1000)
    try {
      await vfs.setattr(path, { atime, mtime })
      return ctx.newNumber(0)
    } catch (err) {
      return ctx.newNumber(-wasiErrno(err))
    }
  })

  defineAsync('__mirage_rename', async (srcH, dstH) => {
    const src = absolute(srcH)
    const dst = absolute(dstH)
    if (vfs === null || !underMount(src) || !underMount(dst)) return ctx.newNumber(-ENOENT)
    // The dispatcher addresses the rename's endpoints against the
    // source's mount, so a cross-mount pair would land inside the
    // wrong tree; the real engine answers -44 (pinned live: each
    // mount is its own preopen and the destination never resolves).
    if (mountOf(src) !== mountOf(dst)) return ctx.newNumber(-ENOENT)
    try {
      await vfs.rename(src, dst)
      return ctx.newNumber(0)
    } catch (err) {
      return ctx.newNumber(-wasiErrno(err))
    }
  })

  defineAsync('__mirage_stat', (pathH) => stat(ctx, vfs, absolute(pathH)))
}
