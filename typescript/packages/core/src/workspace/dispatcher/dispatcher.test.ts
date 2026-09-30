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

import { setFlagsFromString } from 'node:v8'
import { runInNewContext } from 'node:vm'
import { describe, expect, it, vi } from 'vitest'
import { CommandTimeoutError, LimitExceededError } from '../../commands/errors.ts'
import { CachableAsyncIterator } from '../../io/cachable_iterator.ts'
import { ReadStream } from '../../io/read_stream.ts'
import { materialize, OpReport } from '../../io/types.ts'
import { runWithSession } from '../../context/session_context.ts'
import { revisionFor } from '../../observe/context.ts'
import { OpsRegistry, type RegisteredOp } from '../../ops/registry.ts'
import type { Policy } from '../../policy/base.ts'
import { RESULT_BLIND, type ResultBlind } from '../../policy/mixin.ts'
import type { Action, OpsContext, OpsResultContext } from '../../policy/types.ts'
import { POLICY_WRITE_OPS } from './constants.ts'
import type { Dispatcher } from './dispatcher.ts'
import { RAMVFS } from '../../vfs/ram/ram.ts'
import { FileStat, FileType, Limit, MountMode, OnExceed, PathSpec } from '../../types.ts'
import { getTestParser } from '../fixtures/workspace_fixture.ts'
import { SessionState } from '../session/session.ts'
import { Workspace } from '../workspace/workspace.ts'

const ENC = new TextEncoder()
const DEC = new TextDecoder()

describe('dispatch applies limits on the executing mount', () => {
  it('a symlink into a limited mount gets the target mount limit', async () => {
    const parser = await getTestParser()
    const data = new RAMVFS()
    const plain = new RAMVFS()
    const ws = new Workspace(
      {
        '/data': [data, MountMode.EXEC, { read: new Limit({ maxBytes: 8 }) }],
        '/r': plain,
      },
      { mode: MountMode.EXEC, shellParserFactory: () => Promise.resolve(parser) },
    )
    try {
      await ws.shell('echo 0123456789abcdef > /data/big.txt')
      await ws.shell('ln -s /data/big.txt /r/link')
      const direct = (await ws.dispatch('read', '/data/big.txt')) as Uint8Array
      const viaLink = (await ws.dispatch('read', '/r/link')) as Uint8Array
      // The link lives on the unlimited mount, but the read executes
      // on /data: its maxBytes cap must apply either way.
      expect(DEC.decode(viaLink)).toBe(DEC.decode(direct))
      expect(direct.byteLength).toBeLessThan(ENC.encode('0123456789abcdef\n').byteLength)
    } finally {
      await ws.close()
    }
  }, 30_000)
})

describe('dispatch rename addresses dst against the source mount', () => {
  it('cross-mount dst is refused like Python refuses it (EXDEV is a follow-up)', async () => {
    const parser = await getTestParser()
    const ws = new Workspace(
      { '/a': new RAMVFS(), '/b': new RAMVFS() },
      { mode: MountMode.EXEC, shellParserFactory: () => Promise.resolve(parser) },
    )
    try {
      await ws.shell('echo moved-bytes > /a/x.txt')
      // Both languages execute the rename on the source backend and address
      // the dst key against it, so '/b/y.txt' means 'b/y.txt' inside /a, a
      // directory that does not exist there. The store-backed backends
      // refuse (rename(2) ENOENT) instead of growing an orphan key under a
      // directory they never recorded. Neither language crosses mounts.
      await expect(
        ws.dispatch('rename', '/a/x.txt', [PathSpec.fromStrPath('/b/y.txt')]),
      ).rejects.toMatchObject({ code: 'ENOENT' })
      expect(DEC.decode((await ws.shell('cat /a/x.txt')).stdout)).toBe('moved-bytes\n')
      expect((await ws.shell('cat /a/b/y.txt')).exitCode).not.toBe(0)
      expect((await ws.shell('cat /b/y.txt')).exitCode).not.toBe(0)
    } finally {
      await ws.close()
    }
  }, 30_000)
})

describe('dispatch resolves filetype-registered ops by path extension', () => {
  it('a read op keyed to a rendered filetype wins over the plain read', async () => {
    // gdocs/gsheets/gslides/gmail register their rendered reads under a
    // compound filetype; Python reaches them because its dispatcher goes
    // through Mount.execute_op, which stamps the extension. The TS
    // dispatcher must stamp it the same way or every dispatch-based path
    // (crossmount relay, FUSE) misses the op.
    const parser = await getTestParser()
    const ram = new RAMVFS()
    const registry = new OpsRegistry()
    registry.registerVfs(ram)
    registry.register({
      name: 'read',
      vfs: 'ram',
      filetype: '.gdoc.json',
      write: false,
      fn: () => Promise.resolve(ENC.encode('rendered')),
    })
    const ws = new Workspace(
      { '/m': ram },
      { mode: MountMode.EXEC, ops: registry, shellParserFactory: () => Promise.resolve(parser) },
    )
    try {
      await ws.shell('echo raw > /m/doc.gdoc.json')
      const bytes = (await ws.dispatch('read', '/m/doc.gdoc.json')) as Uint8Array
      expect(DEC.decode(bytes)).toBe('rendered')
    } finally {
      await ws.close()
    }
  }, 30_000)
})

describe('unlink of a namespace link', () => {
  it('removes the link, which no backend can see', async () => {
    // The door creates links (`symlink`), so it has to remove them too: a
    // link has no backend entry, so forwarding the unlink reaches a backend
    // that has never heard of the name and answers ENOENT, leaving the link
    // in place. That is what left `git checkout` unable to drop a link the
    // other branch does not have.
    const parser = await getTestParser()
    const ram = new RAMVFS()
    const ws = new Workspace(
      { '/ram': ram },
      { mode: MountMode.WRITE, shellParserFactory: () => Promise.resolve(parser) },
    )
    try {
      await ws.shell('echo hi > /ram/a.txt')
      await ws.shell('ln -s a.txt /ram/link')
      await ws.dispatch('unlink', '/ram/link')
      const listing = await ws.shell('ls /ram')
      expect(DEC.decode(listing.stdout)).not.toContain('link')
    } finally {
      await ws.close()
    }
  })

  it('still reaches the backend for an ordinary file', async () => {
    const parser = await getTestParser()
    const ram = new RAMVFS()
    const ws = new Workspace(
      { '/ram': ram },
      { mode: MountMode.WRITE, shellParserFactory: () => Promise.resolve(parser) },
    )
    try {
      await ws.shell('echo hi > /ram/a.txt')
      await ws.dispatch('unlink', '/ram/a.txt')
      const listing = await ws.shell('ls /ram')
      expect(DEC.decode(listing.stdout).trim()).toBe('')
    } finally {
      await ws.close()
    }
  })
})

describe('the node table answers every verb that names a link', () => {
  async function linkWorkspace(): Promise<Workspace> {
    const parser = await getTestParser()
    const ram = new RAMVFS()
    const ws = new Workspace(
      { '/ram': ram },
      { mode: MountMode.WRITE, shellParserFactory: () => Promise.resolve(parser) },
    )
    await ws.shell('echo hi > /ram/a.txt')
    await ws.shell('mkdir /ram/d')
    await ws.shell('ln -s a.txt /ram/link')
    return ws
  }

  it('renames the link, which no backend can see', async () => {
    // Same fact as the unlink above, one verb along: a guest's rename of
    // a link forwarded to a backend that had never heard of the name, so
    // it answered ENOENT with the link still under the old one.
    const ws = await linkWorkspace()
    try {
      await ws.dispatch('rename', '/ram/link', [PathSpec.fromStrPath('/ram/moved')])
      expect(DEC.decode((await ws.shell('readlink /ram/moved')).stdout)).toBe('a.txt\n')
      expect((await ws.shell('readlink /ram/link')).exitCode).toBe(1)
    } finally {
      await ws.close()
    }
  })

  it('carries the nodes below a renamed directory', async () => {
    // A rename re-anchors a whole subtree, and the part of it no backend can
    // see has to move with it: the link below the source used to stay at a
    // name the rename had emptied, so the moved directory was missing it and
    // the old name still answered readlink.
    const ws = await linkWorkspace()
    try {
      await ws.shell('echo hi > /ram/d/a.txt')
      await ws.shell('ln -s a.txt /ram/d/inner')
      await ws.dispatch('rename', '/ram/d', [PathSpec.fromStrPath('/ram/e')])
      expect(DEC.decode((await ws.shell('readlink /ram/e/inner')).stdout)).toBe('a.txt\n')
      expect((await ws.shell('readlink /ram/d/inner')).exitCode).toBe(1)
    } finally {
      await ws.close()
    }
  })

  it('refuses a rename destination holding a link', async () => {
    // A link is a directory entry no backend can see, so a destination the
    // backend reads as empty is not: POSIX rename(2) answers ENOTEMPTY for it
    // (probed on debian:stable-slim, where a directory holding one broken
    // symlink refuses the rename). Letting the backend decide replaced the
    // directory and deleted the link with it, which loses namespace state
    // where the kernel refuses.
    const ws = await linkWorkspace()
    try {
      await ws.shell('echo hi > /ram/d/a.txt')
      await ws.shell('ln -s a.txt /ram/d/inner')
      await ws.shell('mkdir /ram/e')
      await ws.shell('ln -s gone /ram/e/stale')
      await expect(
        ws.dispatch('rename', '/ram/d', [PathSpec.fromStrPath('/ram/e')]),
      ).rejects.toMatchObject({ code: 'ENOTEMPTY' })
      // Nothing moved: both ends are as they were.
      expect(DEC.decode((await ws.shell('readlink /ram/e/stale')).stdout)).toBe('gone\n')
      expect(DEC.decode((await ws.shell('readlink /ram/d/inner')).stdout)).toBe('a.txt\n')
    } finally {
      await ws.close()
    }
  })

  it('replaces an empty rename destination', async () => {
    // The other half of rename(2): a destination with nothing in it is
    // replaced, and the subtree re-anchors onto the new name.
    const ws = await linkWorkspace()
    try {
      await ws.shell('echo hi > /ram/d/a.txt')
      await ws.shell('ln -s a.txt /ram/d/inner')
      await ws.shell('mkdir /ram/e')
      await ws.dispatch('rename', '/ram/d', [PathSpec.fromStrPath('/ram/e')])
      expect(DEC.decode((await ws.shell('readlink /ram/e/inner')).stdout)).toBe('a.txt\n')
      expect((await ws.shell('readlink /ram/d/inner')).exitCode).toBe(1)
    } finally {
      await ws.close()
    }
  })

  it('answers a no-follow stat with the link row', async () => {
    // lstat asks for the row only the node table holds; a following stat
    // arrives resolved to the target and must not see a link at all.
    const ws = await linkWorkspace()
    try {
      const row = (await ws.dispatch('stat', '/ram/link', [], { nofollow: true })) as {
        type: string
        size: number
      }
      expect(row.type).toBe('symlink')
      expect(row.size).toBe('a.txt'.length)
      const followed = (await ws.dispatch('stat', '/ram/link')) as { type: string }
      expect(followed.type).not.toBe('symlink')
    } finally {
      await ws.close()
    }
  })

  it('replaces a link that sits at a rename destination', async () => {
    // rename(2) replaces the destination. A link left in the table there
    // shadowed the file that had just landed: the listing showed the new
    // file, every read followed the old link, and the moved content was
    // reachable under no name at all. mv did this right at the command
    // tier, so only the surfaces below it (a guest, a kernel mount) saw
    // the broken state.
    const ws = await linkWorkspace()
    try {
      await ws.dispatch('rename', '/ram/a.txt', [PathSpec.fromStrPath('/ram/link')])
      expect(DEC.decode((await ws.shell('cat /ram/link')).stdout)).toBe('hi\n')
      expect((await ws.shell('readlink /ram/link')).exitCode).toBe(1)
    } finally {
      await ws.close()
    }
  })

  it('refuses a symlink onto a name that is taken', async () => {
    // symlink(2) is EEXIST on an occupied name, and only the door can
    // tell: a file and a directory are the backend's, a link is the node
    // table's, and a mount root is the registry's. Unchecked, the node
    // went on top and buried whatever was there.
    const ws = await linkWorkspace()
    try {
      for (const occupied of ['/ram/a.txt', '/ram/d', '/ram/link', '/ram']) {
        await expect(
          ws.dispatch('symlink', occupied, [], { target: 'elsewhere' }),
        ).rejects.toMatchObject({ code: 'EEXIST' })
      }
      expect(DEC.decode((await ws.shell('cat /ram/a.txt')).stdout)).toBe('hi\n')
    } finally {
      await ws.close()
    }
  })

  it('refuses a symlink whose parent cannot hold it', async () => {
    // symlink(2) resolves the directory a name goes in before the name:
    // ENOENT when it is absent, ENOTDIR when a plain file stands in the
    // chain at any depth, and a link above the name is followed first.
    // Unchecked, the node was an orphan that invented the directories above
    // it, which ls then listed.
    const ws = await linkWorkspace()
    try {
      await ws.shell('ln -s missing /ram/dangling')
      const cases: [string, string][] = [
        ['/ram/nope/y', 'ENOENT'],
        ['/ram/nope/deeper/y', 'ENOENT'],
        ['/ram/dangling/y', 'ENOENT'],
        ['/ram/a.txt/y', 'ENOTDIR'],
        ['/ram/a.txt/sub/y', 'ENOTDIR'],
        ['/ram/link/y', 'ENOTDIR'],
      ]
      for (const [name, code] of cases) {
        await expect(ws.dispatch('symlink', name, [], { target: 'x' })).rejects.toMatchObject({
          code,
        })
      }
      expect([...ws.namespace.symlinkTargets().keys()].sort()).toEqual([
        '/ram/dangling',
        '/ram/link',
      ])
      expect(DEC.decode((await ws.shell('ls /ram')).stdout)).toBe('a.txt\nd\ndangling\nlink\n')
    } finally {
      await ws.close()
    }
  })

  it('files a link made under a linked directory in its target', async () => {
    // Every link above the final name is followed before the op sees the
    // path, whichever surface named it. The node table filed a relative
    // `ln -s t alias/x` under the alias's own name, where no listing of the
    // directory and no read through it ever looked.
    const ws = await linkWorkspace()
    try {
      await ws.shell('mkdir /ram/e; ln -s d /ram/alias')
      await ws.dispatch('symlink', '/ram/alias/x', [], { target: 't' })
      await ws.dispatch('symlink', '/ram/e/empty', [], { target: 't' })
      expect(ws.namespace.readlink('/ram/d/x')).toBe('t')
      expect(ws.namespace.isLink('/ram/alias/x')).toBe(false)
      expect(await ws.dispatch('readlink', '/ram/alias/x')).toBe('t')
      expect(ws.namespace.readlink('/ram/e/empty')).toBe('t')
    } finally {
      await ws.close()
    }
  })

  it('refuses a link rename whose landing parent cannot hold it', async () => {
    // rename(2) resolves the destination's directory as symlink(2) does,
    // and the node table moved a link anywhere at all.
    const ws = await linkWorkspace()
    try {
      for (const [landing, code] of [
        ['/ram/nope/x', 'ENOENT'],
        ['/ram/a.txt/x', 'ENOTDIR'],
      ] as const) {
        await expect(
          ws.dispatch('rename', '/ram/link', [PathSpec.fromStrPath(landing)]),
        ).rejects.toMatchObject({ code })
        expect(ws.namespace.isLink(landing)).toBe(false)
      }
      expect(ws.namespace.readlink('/ram/link')).toBe('a.txt')
    } finally {
      await ws.close()
    }
  })
})

describe('the fenced remnant cascade rides the mount revisions', () => {
  it('a fenced backend op reads the pinned revision', async () => {
    // fencedCall reruns backend ops outside `dispatch`, and Python's
    // twin routes them through `Mount.execute_op`, which binds the
    // mount prefix AND the revision pins. A fenced readdir/stat that
    // reads unpinned answers from the wrong version of a
    // revision-pinned mount, so the binding is pinned here through the
    // one public trigger: an rmdir whose only remnants the session
    // cannot see.
    const parser = await getTestParser()
    const ram = new RAMVFS()
    const registry = new OpsRegistry()
    registry.registerVfs(ram)
    const ws = new Workspace(
      { '/ram': ram },
      { mode: MountMode.WRITE, ops: registry, shellParserFactory: () => Promise.resolve(parser) },
    )
    try {
      await ws.shell('mkdir /ram/d && echo x > /ram/d/h.txt')
      // Mounting re-registers the VFS's ops (workspace.ts), so the
      // probe wraps readdir only after construction, or it is clobbered.
      const original = registry.find('readdir', 'ram')
      if (original === null) throw new Error('ram readdir op missing')
      const originalFn = original.fn
      let seen: string | null | undefined
      registry.register({
        ...original,
        fn: (...args: Parameters<typeof originalFn>) => {
          seen = revisionFor('/ram/d/h.txt')
          return originalFn(...args)
        },
      })
      const internals = ws as unknown as {
        registry: { mountFor(path: string): { revisions: Map<string, string> } }
      }
      internals.registry.mountFor('/ram/d').revisions.set('/ram/d/h.txt', 'r1')
      const sess = new SessionState({
        sessionId: 'agent',
        hiddenPaths: { paths: ['/ram/d/h.txt'] },
      })
      await runWithSession(sess, () => ws.dispatch('rmdir', '/ram/d'))
      expect(seen).toBe('r1')
    } finally {
      await ws.close()
    }
  }, 30_000)
})

describe('the turf mode gates the node table', () => {
  it('a read grant refuses link writes like file writes', async () => {
    // The mode gate on the table ops. A read grant refused a file's
    // unlink with EROFS while the same session deleted, created and
    // renamed its sibling link: the table verbs ran no mode check at
    // all, so `mounts: {"/extra": "read"}` protected everything on the
    // mount except its names.
    const parser = await getTestParser()
    const ws = new Workspace(
      { '/extra': new RAMVFS() },
      { mode: MountMode.WRITE, shellParserFactory: () => Promise.resolve(parser) },
    )
    try {
      await ws.shell('echo b > /extra/plain.txt')
      await ws.shell('ln -s plain.txt /extra/lk')
      const sess = ws.createSession('agent', { mounts: { '/extra/': 'read' } })
      await runWithSession(sess, async () => {
        await expect(ws.dispatch('unlink', '/extra/lk')).rejects.toMatchObject({
          code: 'EROFS',
        })
        await expect(
          ws.dispatch('symlink', '/extra/lk2', [], { target: 'plain.txt' }),
        ).rejects.toMatchObject({ code: 'EROFS' })
        await expect(
          ws.dispatch('rename', '/extra/lk', [PathSpec.fromStrPath('/extra/mv')]),
        ).rejects.toMatchObject({ code: 'EROFS' })
      })
      expect(DEC.decode((await ws.shell('readlink /extra/lk')).stdout)).toBe('plain.txt\n')
      expect((await ws.shell('readlink /extra/lk2')).exitCode).toBe(1)
    } finally {
      await ws.close()
    }
  })

  it.each([...POLICY_WRITE_OPS])('%s refuses before backend support and I/O', async (op) => {
    const ws = new Workspace({ '/ro': [new RAMVFS(), MountMode.READ] })
    try {
      const mount = ws.namespace.mountFor('/ro/file')
      const ready = vi.spyOn(mount, 'ensureReady').mockRejectedValue(new Error('backend reached'))
      await expect(ws.dispatch(op, '/ro/file')).rejects.toMatchObject({ code: 'EROFS' })
      expect(ready).not.toHaveBeenCalled()
      expect(ws.namespace.isLink('/ro/file')).toBe(false)
    } finally {
      await ws.close()
    }
  })

  it('a rename destination is judged on its own turf', async () => {
    // The endpoints need not share a turf, and each is scored against
    // its own prefix: a grant writing /rw but only reading /ro refuses,
    // blaming the destination, the way the backend gate checks both ends
    // of a rename. The grant is what binds, so both mounts are writable
    // and the session is the only thing narrowing either.
    const parser = await getTestParser()
    const ws = new Workspace(
      { '/rw': new RAMVFS(), '/ro': new RAMVFS() },
      { mode: MountMode.WRITE, shellParserFactory: () => Promise.resolve(parser) },
    )
    try {
      await ws.shell('ln -s t /rw/lk')
      const sess = ws.createSession('agent', {
        mounts: { '/rw/': 'write', '/ro/': 'read' },
      })
      await runWithSession(sess, async () => {
        await expect(
          ws.dispatch('rename', '/rw/lk', [PathSpec.fromStrPath('/ro/lk')]),
        ).rejects.toMatchObject({ code: 'EROFS', virtualPath: '/ro/lk' })
      })
      expect(ws.namespace.isLink('/rw/lk')).toBe(true)
    } finally {
      await ws.close()
    }
  })
})

describe('a rename moves what the node table holds', () => {
  it('carries the node at the source itself', async () => {
    // The subtree below the source was re-anchored and the source's own
    // node was not, so an overlay recorded there stayed at the emptied
    // name: it never reached the landing, and whatever was created at
    // the old name next inherited it.
    const parser = await getTestParser()
    const ws = new Workspace(
      { '/a': new RAMVFS() },
      { mode: MountMode.WRITE, shellParserFactory: () => Promise.resolve(parser) },
    )
    try {
      await ws.shell('printf one > /a/f.txt')
      await ws.namespace.setAttrs('/a/f.txt', { mode: 0o400 })
      await ws.dispatch('rename', '/a/f.txt', [PathSpec.fromStrPath('/a/g.txt')])
      expect(ws.namespace.metaFor('/a/f.txt')).toBeNull()
      expect(ws.namespace.metaFor('/a/g.txt')?.mode).toBe(0o400)
    } finally {
      await ws.close()
    }
  })

  it('replaces the node at the landing', async () => {
    // rename(2) replaces the destination, so the overlay it carried
    // goes with it rather than staying to shadow what just landed.
    const parser = await getTestParser()
    const ws = new Workspace(
      { '/a': new RAMVFS() },
      { mode: MountMode.WRITE, shellParserFactory: () => Promise.resolve(parser) },
    )
    try {
      await ws.shell('printf one > /a/f.txt && printf two > /a/g.txt')
      await ws.namespace.setAttrs('/a/g.txt', { mode: 0o400 })
      await ws.dispatch('rename', '/a/f.txt', [PathSpec.fromStrPath('/a/g.txt')])
      expect(ws.namespace.metaFor('/a/g.txt')).toBeNull()
    } finally {
      await ws.close()
    }
  })
})

describe('a hide answers a create by what its parent answers', () => {
  it('under a hidden directory a create is ENOENT, at a hidden name under a visible one EACCES', async () => {
    // Every read on a hidden directory answered ENOENT while a create
    // beneath it answered EACCES, so a session could map a profile's
    // hidden prefixes by probing writes. The parent decides, a rename
    // destination is a create, and the shell's redirect renders the
    // same refusal an ordinary missing directory does.
    const parser = await getTestParser()
    const ws = new Workspace(
      { '/ram': new RAMVFS() },
      { mode: MountMode.WRITE, shellParserFactory: () => Promise.resolve(parser) },
    )
    try {
      await ws.shell(
        'mkdir -p /ram/vault /ram/open && echo s > /ram/vault/secret && echo p > /ram/open/pub.txt && echo q > /ram/open/q.txt',
      )
      const sess = ws.createSession('agent', {
        profile: { paths: { hide: ['/ram/vault', '/ram/open/pub.txt'] } },
      })
      await runWithSession(sess, async () => {
        await expect(
          ws.dispatch('write', '/ram/vault/new.txt', [ENC.encode('x')]),
        ).rejects.toMatchObject({ code: 'ENOENT' })
        await expect(ws.dispatch('mkdir', '/ram/vault/deeper')).rejects.toMatchObject({
          code: 'ENOENT',
        })
        // truncate creates a missing file at the requested length, so
        // it is a create too.
        await expect(ws.dispatch('truncate', '/ram/vault/new.txt', [0])).rejects.toMatchObject({
          code: 'ENOENT',
        })
        await expect(ws.dispatch('truncate', '/ram/open/pub.txt', [0])).rejects.toMatchObject({
          code: 'EACCES',
        })
        await expect(
          ws.dispatch('rename', '/ram/open/q.txt', [PathSpec.fromStrPath('/ram/vault/moved')]),
        ).rejects.toMatchObject({ code: 'ENOENT' })
        await expect(ws.dispatch('mkdir', '/ram/vault')).rejects.toMatchObject({ code: 'EACCES' })
        await expect(
          ws.dispatch('write', '/ram/open/pub.txt', [ENC.encode('x')]),
        ).rejects.toMatchObject({ code: 'EACCES' })
        await expect(
          ws.dispatch('rename', '/ram/open/q.txt', [PathSpec.fromStrPath('/ram/open/pub.txt')]),
        ).rejects.toMatchObject({ code: 'EACCES' })
      })
      const under = await ws.shell('echo x > /ram/vault/new.txt', { sessionId: 'agent' })
      expect(DEC.decode(under.stderr)).toBe('/ram/vault/new.txt: No such file or directory\n')
      const control = await ws.shell('echo x > /ram/ghost/new.txt', { sessionId: 'agent' })
      expect(DEC.decode(control.stderr)).toBe('/ram/ghost/new.txt: No such file or directory\n')
      expect(DEC.decode((await ws.shell('cat /ram/vault/secret')).stdout)).toBe('s\n')
    } finally {
      await ws.close()
    }
  })
})

describe('a failed backend probe is not evidence of absence', () => {
  it('symlink refuses a name whose backend could not answer', async () => {
    const parser = await getTestParser()
    class BrokenVFS extends RAMVFS {
      override ops(): readonly RegisteredOp[] {
        return super
          .ops()
          .map((op) =>
            op.name === 'stat'
              ? { ...op, fn: () => Promise.reject(new Error('401 bad credentials')) }
              : op,
          )
      }
    }
    const broken = new BrokenVFS()
    const ws = new Workspace(
      { '/r': new RAMVFS(), '/data': broken },
      { mode: MountMode.EXEC, shellParserFactory: () => Promise.resolve(parser) },
    )
    try {
      // The door probes the name before linking over it. A backend that
      // cannot answer has not reported the name free, so the link must not
      // be created on the strength of that failure.
      await expect(
        ws.dispatch('symlink', '/data/notes.txt', [], { target: '/r/t' }),
      ).rejects.toThrow('401 bad credentials')
    } finally {
      await ws.close()
    }
  }, 30_000)

  it('a failing parent listing propagates out of the parent-listing probe', async () => {
    const parser = await getTestParser()
    const listing = new RAMVFS()
    // The store's key iteration is reached only by the parent readdir, not
    // by the stat probe ahead of it, so this fails exactly the one channel.
    vi.spyOn(listing.store.files, 'keys').mockImplementation(() => {
      throw new Error('backend listing failed')
    })
    const ws = new Workspace(
      { '/r': new RAMVFS(), '/data': listing },
      { mode: MountMode.EXEC, shellParserFactory: () => Promise.resolve(parser) },
    )
    try {
      // The stat probe misses on a name RAM does not hold, which is the
      // one route into the parent-listing probe. The parent's readdir is
      // the channel that fails there, and a channel that could not answer
      // is not a name reported free.
      await expect(
        ws.dispatch('symlink', '/data/notes.txt', [], { target: '/r/t' }),
      ).rejects.toThrow('backend listing failed')
    } finally {
      await ws.close()
    }
  }, 30_000)

  it('readlink still answers ENOENT where no mount serves the path', async () => {
    const parser = await getTestParser()
    const ws = new Workspace(
      { '/r': new RAMVFS() },
      { mode: MountMode.EXEC, shellParserFactory: () => Promise.resolve(parser) },
    )
    try {
      await expect(ws.dispatch('readlink', '/nowhere/x')).rejects.toMatchObject({ code: 'ENOENT' })
    } finally {
      await ws.close()
    }
  }, 30_000)
})

describe('the door answers extended attributes from the node table', () => {
  const open = async (): Promise<Workspace> => {
    const parser = await getTestParser()
    const ws = new Workspace(
      { '/r': new RAMVFS() },
      { mode: MountMode.WRITE, shellParserFactory: () => Promise.resolve(parser) },
    )
    await ws.shell('printf x > /r/f && ln -s f /r/lk')
    return ws
  }

  it('stores them on the node and lists them sorted', async () => {
    const ws = await open()
    try {
      await ws.vfs.setxattr('/r/f', 'user.b', ENC.encode('two'))
      await ws.vfs.setxattr('/r/f', 'user.a', ENC.encode('one'))
      expect(await ws.vfs.listxattr('/r/f')).toEqual(['user.a', 'user.b'])
      expect(DEC.decode(await ws.vfs.getxattr('/r/f', 'user.b'))).toBe('two')
      await ws.vfs.removexattr('/r/f', 'user.b')
      expect(await ws.vfs.listxattr('/r/f')).toEqual(['user.a'])
      await expect(ws.vfs.getxattr('/r/f', 'user.b')).rejects.toMatchObject({ code: 'ENODATA' })
    } finally {
      await ws.close()
    }
  })

  it('refuses the way setxattr(2) does for its flags', async () => {
    const ws = await open()
    try {
      await ws.vfs.setxattr('/r/f', 'user.a', ENC.encode('one'))
      await expect(
        ws.vfs.setxattr('/r/f', 'user.a', ENC.encode('two'), { create: true }),
      ).rejects.toMatchObject({ code: 'EEXIST' })
      await expect(
        ws.vfs.setxattr('/r/f', 'user.q', ENC.encode('x'), { replace: true }),
      ).rejects.toMatchObject({ code: 'ENODATA' })
      await ws.vfs.setxattr('/r/f', 'user.a', ENC.encode('two'), { replace: true })
      expect(DEC.decode(await ws.vfs.getxattr('/r/f', 'user.a'))).toBe('two')
    } finally {
      await ws.close()
    }
  })

  it('answers ENOENT for a missing path and stores nothing there', async () => {
    const ws = await open()
    try {
      await expect(ws.vfs.listxattr('/r/nope')).rejects.toMatchObject({ code: 'ENOENT' })
      await expect(ws.vfs.setxattr('/r/nope', 'user.a', ENC.encode('x'))).rejects.toMatchObject({
        code: 'ENOENT',
      })
      expect(ws.namespace.metaFor('/r/nope')).toBeNull()
    } finally {
      await ws.close()
    }
  })

  it('drops them with the file and carries them through a rename', async () => {
    // Removed through the door rather than the shell's rm, the node
    // stayed, and a file created at the name next read back the old
    // file's attributes.
    const ws = await open()
    try {
      await ws.vfs.setxattr('/r/f', 'user.a', ENC.encode('one'))
      await ws.vfs.rename('/r/f', '/r/g')
      expect(DEC.decode(await ws.vfs.getxattr('/r/g', 'user.a'))).toBe('one')
      expect(ws.namespace.metaFor('/r/f')).toBeNull()
      await ws.vfs.unlink('/r/g')
      await ws.shell('printf y > /r/g')
      expect(await ws.vfs.listxattr('/r/g')).toEqual([])
    } finally {
      await ws.close()
    }
  })

  it('reads a link node itself under nofollow', async () => {
    const ws = await open()
    try {
      await ws.vfs.setxattr('/r/lk', 'user.target', ENC.encode('t'))
      await ws.vfs.setxattr('/r/lk', 'user.own', ENC.encode('o'), { nofollow: true })
      expect(await ws.vfs.listxattr('/r/lk')).toEqual(['user.target'])
      expect(await ws.vfs.listxattr('/r/lk', { nofollow: true })).toEqual(['user.own'])
      expect(ws.namespace.readlink('/r/lk')).toBe('f')
    } finally {
      await ws.close()
    }
  })

  it("keeps a backend stat's extra out of the attributes", async () => {
    const ws = await open()
    const stat = vi.spyOn(ws.opsRegistry, 'call')
    stat.mockImplementation(async (op, ...rest) => {
      if (op === 'stat') {
        return new FileStat({ name: 'd', type: FileType.DIRECTORY, extra: { file_id: '1AbC' } })
      }
      return OpsRegistry.prototype.call.call(ws.opsRegistry, op, ...rest)
    })
    try {
      await ws.vfs.setxattr('/r/f', 'user.tag', ENC.encode('t'))
      expect(await ws.vfs.listxattr('/r/f')).toEqual(['user.tag'])
    } finally {
      stat.mockRestore()
      await ws.close()
    }
  })
})

describe('shell mutations share read-only admission', () => {
  it.each([
    ['echo x >> /ro/file', '/ro/file: Read-only file system\n'],
    ['exec >> /ro/file', '/ro/file: Read-only file system\n'],
    [
      'ln -s file /ro/link',
      "ln: failed to create symbolic link '/ro/link': Read-only file system\n",
    ],
    ['chmod 600 /ro/file', "chmod: changing permissions of '/ro/file': Read-only file system\n"],
    ['find /ro/file -delete', "find: cannot delete '/ro/file': Read-only file system\n"],
    ['rm /ro/file', "rm: cannot remove '/ro/file': Read-only file system\n"],
    ['mv /ro/file /ro/moved', "mv: cannot move '/ro/file' to '/ro/moved': Read-only file system\n"],
    ['touch /ro/file', "touch: cannot touch '/ro/file': Read-only file system\n"],
    [
      'truncate -s 0 /ro/file',
      "truncate: cannot open '/ro/file' for writing: Read-only file system\n",
    ],
  ])('%s', async (command, diagnostic) => {
    const parser = await getTestParser()
    const ws = new Workspace(
      { '/ro': new RAMVFS() },
      { mode: MountMode.WRITE, shellParser: parser },
    )
    try {
      await ws.dispatch('write', '/ro/file', [ENC.encode('original')])
      ws.namespace.mountFor('/ro/file').mode = MountMode.READ
      const read = vi.spyOn(ws.opsRegistry, 'call')
      const result = await ws.shell(command)
      expect(result.exitCode).toBe(1)
      expect(DEC.decode(await materialize(result.stderr))).toBe(diagnostic)
      expect(read.mock.calls.some(([op]) => op === 'read' || op === 'read_bytes')).toBe(false)
      expect(ws.namespace.isLink('/ro/link')).toBe(false)
      expect(DEC.decode((await ws.dispatch('read', '/ro/file')) as Uint8Array)).toBe('original')
    } finally {
      await ws.close()
    }
  })
})

describe('rmdir namespace entries', () => {
  it.each([false, true])(
    'accounts for a directory containing only a link (hidden=%s)',
    async (hidden) => {
      const parser = await getTestParser()
      const ws = new Workspace(
        { '/data': new RAMVFS() },
        { mode: MountMode.WRITE, shellParser: parser },
      )
      try {
        await ws.shell('mkdir /data/d; ln -s nowhere /data/d/link')
        const session = ws.createSession('remover', {
          profile: { paths: { hide: hidden ? ['/data/d/link'] : [] } },
        })
        await runWithSession(session, async () => {
          if (hidden) await ws.vfs.rmdir('/data/d')
          else await expect(ws.vfs.rmdir('/data/d')).rejects.toMatchObject({ code: 'ENOTEMPTY' })
        })
        expect(ws.namespace.isLink('/data/d/link')).toBe(!hidden)
      } finally {
        await ws.close()
      }
    },
  )

  it('keeps a link created while the backend removes the directory', async () => {
    const parser = await getTestParser()
    const ws = new Workspace(
      { '/data': new RAMVFS() },
      { mode: MountMode.WRITE, shellParser: parser },
    )
    try {
      await ws.shell('mkdir /data/d; ln -s nowhere /data/d/old')
      const call = ws.opsRegistry.call.bind(ws.opsRegistry)
      vi.spyOn(ws.opsRegistry, 'call').mockImplementation(async (name, ...rest) => {
        if (name === 'rmdir')
          await ws.dispatch('symlink', '/data/d/late', [], { target: 'nowhere' })
        return call(name, ...rest)
      })
      const session = ws.createSession('remover', {
        profile: { paths: { hide: ['/data/d/old'] } },
      })
      await runWithSession(session, () => ws.vfs.rmdir('/data/d'))
      expect(ws.namespace.isLink('/data/d/old')).toBe(false)
      expect(ws.namespace.readlink('/data/d/late')).toBe('nowhere')
    } finally {
      await ws.close()
    }
  })
})

const CHUNK = 64 * 1024
const MIB = 1024 * 1024

interface Pulls {
  opened: number
  chunks: number
  closed: boolean
}

type StreamForm = NonNullable<RegisteredOp['stream']>

function doorOf(ws: Workspace): Dispatcher {
  return (ws as unknown as { dispatcher: Dispatcher }).dispatcher
}

function ramReadOp(ws: Workspace): RegisteredOp & { stream: StreamForm } {
  const original = ws.opsRegistry.find('read', 'ram')
  if (original?.stream === undefined) throw new Error('ram read has no stream form')
  return original as RegisteredOp & { stream: StreamForm }
}

function streamRead(ws: Workspace, body: StreamForm): void {
  ws.opsRegistry.register({ ...ramReadOp(ws), stream: body })
}

function chunkedReads(ws: Workspace, size = CHUNK): Pulls {
  const inner = ramReadOp(ws).stream
  const pulls: Pulls = { opened: 0, chunks: 0, closed: false }
  streamRead(ws, (accessor, path, args, kwargs) => {
    pulls.opened++
    const source = inner(accessor, path, args, kwargs) as AsyncIterable<Uint8Array>
    return (async function* (): AsyncGenerator<Uint8Array> {
      try {
        for await (const whole of source) {
          for (let at = 0; at < whole.byteLength; at += size) {
            pulls.chunks++
            yield whole.subarray(at, at + size)
          }
        }
      } finally {
        pulls.closed = true
      }
    })()
  })
  return pulls
}

function pattern(size: number): Uint8Array {
  return Uint8Array.from({ length: size }, (_, i) => i % 251)
}

async function openStream(
  ws: Workspace,
  path: string,
  kwargs: Record<string, unknown> = {},
): Promise<ReadStream> {
  const stream = await ws.dispatch('read', path, [], { ...kwargs, stream: true })
  expect(stream).toBeInstanceOf(ReadStream)
  return stream as ReadStream
}

async function chunksOf(stream: ReadStream): Promise<Uint8Array[]> {
  const out: Uint8Array[] = []
  for await (const chunk of stream) out.push(chunk)
  return out
}

function joined(chunks: readonly Uint8Array[]): Uint8Array {
  const out = new Uint8Array(chunks.reduce((n, c) => n + c.byteLength, 0))
  let at = 0
  for (const chunk of chunks) {
    out.set(chunk, at)
    at += chunk.byteLength
  }
  return out
}

async function settlesWithin(promise: Promise<unknown>, ms: number): Promise<boolean> {
  let timer: ReturnType<typeof setTimeout> | undefined
  const late = new Promise<boolean>((resolve) => {
    timer = setTimeout(() => {
      resolve(false)
    }, ms)
  })
  try {
    return await Promise.race([promise.then(() => true), late])
  } finally {
    clearTimeout(timer)
  }
}

function exposedGc(): (() => void) | undefined {
  const own = (globalThis as { gc?: () => void }).gc
  if (own !== undefined) return own
  // The flag is process-wide and stays on: resetting it could race another
  // worker's lookup, and a runtime that refuses it just skips the GC cases.
  try {
    setFlagsFromString('--expose-gc')
    const gc: unknown = runInNewContext('typeof gc === "function" ? gc : undefined')
    return typeof gc === 'function' ? (gc as () => void) : undefined
  } catch {
    return undefined
  }
}

const collectGarbage = exposedGc()

async function collectedWithin(settled: () => boolean, rounds = 50): Promise<boolean> {
  for (let i = 0; i < rounds && !settled(); i++) {
    collectGarbage?.()
    await new Promise((resolve) => setTimeout(resolve, 10))
  }
  return settled()
}

class SealReads implements Policy {
  preOps(ctx: OpsContext): Action | null {
    return ctx.op === 'read' ? { kind: 'deny', reason: 'sealed' } : null
  }
}

class DenySecret implements Policy {
  postOps(ctx: OpsResultContext): Action | null {
    const data = ctx.result instanceof Uint8Array ? DEC.decode(ctx.result) : ''
    return ctx.op === 'read' && data.includes('SECRET') ? { kind: 'deny', reason: 'secret' } : null
  }
}

class BlindSeal implements Policy, ResultBlind {
  readonly [RESULT_BLIND] = true as const
  postOps(ctx: OpsResultContext): Action | null {
    return ctx.op === 'read' && ctx.path.virtual.endsWith('.sealed')
      ? { kind: 'deny', reason: 'sealed' }
      : null
  }
}

function ramWorkspace(
  options: {
    limits?: Record<string, Limit>
    policies?: Policy[]
    caches?: boolean
    ram?: RAMVFS
  } = {},
): Workspace {
  const ram = options.ram ?? new RAMVFS()
  if (options.caches === true) Object.assign(ram, { cachesReads: true })
  return new Workspace(
    { '/m': [ram, MountMode.WRITE, options.limits ?? {}] },
    { mode: MountMode.WRITE, policies: options.policies ?? [] },
  )
}

describe('a streamed read through the door', () => {
  it('equals the whole read, for one chunk and for many', async () => {
    const ws = ramWorkspace()
    try {
      await ws.vfs.writeFile('/m/small.txt', 'hello stream\n')
      const small = await openStream(ws, '/m/small.txt')
      expect(DEC.decode(joined(await chunksOf(small)))).toBe('hello stream\n')
      const data = pattern(5 * CHUNK + 17)
      await ws.vfs.writeFile('/m/big.bin', data)
      const pulls = chunkedReads(ws)
      const chunks = await chunksOf(await openStream(ws, '/m/big.bin'))
      expect(chunks.length).toBe(6)
      expect(joined(chunks)).toEqual((await ws.dispatch('read', '/m/big.bin')) as Uint8Array)
      expect(joined(chunks)).toEqual(data)
      expect(pulls.closed).toBe(true)
    } finally {
      await ws.close()
    }
  })

  it('pulls at most two chunks of a large file closed after one, and unmount completes', async () => {
    const ws = ramWorkspace()
    try {
      await ws.vfs.writeFile('/m/big.bin', pattern(MIB))
      const pulls = chunkedReads(ws)
      const report = new OpReport()
      const [stream] = (await doorOf(ws).dispatch(
        'read',
        PathSpec.fromStrPath('/m/big.bin'),
        [],
        { stream: true },
        report,
      )) as [ReadStream, unknown]
      const first = await stream.next()
      expect((first.value as Uint8Array).byteLength).toBe(CHUNK)
      await stream.return()
      expect(pulls.chunks).toBeLessThanOrEqual(2)
      expect(pulls.closed).toBe(true)
      expect(report.bytes).toBeLessThan(MIB)
      expect(await settlesWithin(ws.unmount('/m'), 2000)).toBe(true)
    } finally {
      await ws.close()
    }
  })

  it('refuses a missing file at the dispatch call and tells the reconciler', async () => {
    const ws = ramWorkspace()
    try {
      const missing = vi.spyOn(doorOf(ws).reconciler, 'onOpMissing')
      await expect(ws.dispatch('read', '/m/nope.txt', [], { stream: true })).rejects.toMatchObject({
        code: 'ENOENT',
      })
      expect(missing).toHaveBeenCalledOnce()
      expect(missing.mock.calls[0]?.slice(1, 3)).toEqual(['read', '/m/nope.txt'])
      expect(missing.mock.calls[0]?.[3]).toMatchObject({ code: 'ENOENT' })
    } finally {
      await ws.close()
    }
  })

  it('refuses a hidden path as absent and a pre-denied read, opening no backend', async () => {
    const ws = ramWorkspace()
    try {
      await ws.vfs.writeFile('/m/secret.txt', 's')
      const pulls = chunkedReads(ws)
      const sess = ws.createSession('agent', { profile: { paths: { hide: ['/m/secret.txt'] } } })
      await runWithSession(sess, async () => {
        await expect(
          ws.dispatch('read', '/m/secret.txt', [], { stream: true }),
        ).rejects.toMatchObject({ code: 'ENOENT' })
      })
      expect(pulls.opened).toBe(0)
    } finally {
      await ws.close()
    }
    const sealed = ramWorkspace({ policies: [new SealReads()] })
    try {
      await sealed.vfs.writeFile('/m/a.txt', 'a')
      const pulls = chunkedReads(sealed)
      await expect(sealed.dispatch('read', '/m/a.txt', [], { stream: true })).rejects.toMatchObject(
        { code: 'EACCES' },
      )
      expect(pulls.opened).toBe(0)
    } finally {
      await sealed.close()
    }
  })

  it('serves a warm cache as one chunk and streams a raw read from the backend', async () => {
    const ws = ramWorkspace({ caches: true })
    try {
      await ws.vfs.writeFile('/m/doc.txt', 'STORED')
      await ws.cache.set('/m/doc.txt', ENC.encode('CACHED'), { ttl: 600 })
      const pulls = chunkedReads(ws)
      const warm = await chunksOf(await openStream(ws, '/m/doc.txt'))
      expect(warm.map((c) => DEC.decode(c))).toEqual(['CACHED'])
      expect(pulls.opened).toBe(0)
      const raw = await chunksOf(await openStream(ws, '/m/doc.txt', { filetype: null }))
      expect(DEC.decode(joined(raw))).toBe('STORED')
      expect(pulls.opened).toBe(1)
    } finally {
      await ws.close()
    }
  })

  it('lets a filetype renderer win, and a raw stream yields the stored bytes', async () => {
    const ws = ramWorkspace()
    try {
      ws.opsRegistry.register({
        name: 'read',
        vfs: 'ram',
        filetype: '.tally',
        write: false,
        fn: () => Promise.resolve(ENC.encode('RENDERED')),
      })
      await ws.vfs.writeFile('/m/books.tally', 'STORED')
      const rendered = await chunksOf(await openStream(ws, '/m/books.tally'))
      expect(rendered.map((c) => DEC.decode(c))).toEqual(['RENDERED'])
      const raw = await chunksOf(await openStream(ws, '/m/books.tally', { filetype: null }))
      expect(DEC.decode(joined(raw))).toBe('STORED')
    } finally {
      await ws.close()
    }
  })

  it('serves a window as one chunk holding the slice', async () => {
    const ws = ramWorkspace()
    try {
      await ws.vfs.writeFile('/m/r.txt', '0123456789')
      const pulls = chunkedReads(ws)
      const window = await chunksOf(await openStream(ws, '/m/r.txt', { offset: 2, size: 3 }))
      expect(window.map((c) => DEC.decode(c))).toEqual(['234'])
      expect(pulls.opened).toBe(0)
    } finally {
      await ws.close()
    }
  })

  it('cuts a truncating read cap as it flows and stops the backend early', async () => {
    const ws = ramWorkspace({ limits: { read: new Limit({ maxBytes: 100 }) } })
    try {
      await ws.vfs.writeFile('/m/big.bin', pattern(1024))
      const pulls = chunkedReads(ws, 64)
      const report = new OpReport()
      const [stream] = (await doorOf(ws).dispatch(
        'read',
        PathSpec.fromStrPath('/m/big.bin'),
        [],
        { stream: true },
        report,
      )) as [ReadStream, unknown]
      expect(joined(await chunksOf(stream))).toEqual(pattern(1024).subarray(0, 100))
      expect(pulls.chunks).toBe(2)
      expect(pulls.closed).toBe(true)
      expect(report.bytes).toBe(128)
    } finally {
      await ws.close()
    }
  })

  it('refuses a file over an erroring read cap at dispatch and serves one under it whole', async () => {
    const ws = ramWorkspace({
      limits: { read: new Limit({ maxBytes: 100, onExceed: OnExceed.ERROR }) },
    })
    try {
      await ws.vfs.writeFile('/m/big.bin', pattern(1024))
      await ws.vfs.writeFile('/m/small.bin', pattern(90))
      const pulls = chunkedReads(ws, 64)
      await expect(ws.dispatch('read', '/m/big.bin', [], { stream: true })).rejects.toThrow(
        LimitExceededError,
      )
      expect(pulls.chunks).toBe(2)
      expect(pulls.closed).toBe(true)
      const small = await chunksOf(await openStream(ws, '/m/small.bin'))
      expect(small.length).toBe(1)
      expect(joined(small)).toEqual(pattern(90))
    } finally {
      await ws.close()
    }
  })

  it('hands a content-reading post policy the bytes, so it still denies a streamed read', async () => {
    const ws = ramWorkspace()
    try {
      expect(ws.policies.readsResults()).toBe(false)
      ws.policies.add(new DenySecret())
      expect(ws.policies.readsResults()).toBe(true)
      await ws.vfs.writeFile('/m/leak.txt', 'x'.repeat(130) + 'SECRET')
      await ws.vfs.writeFile('/m/plans.txt', 'y'.repeat(200))
      const pulls = chunkedReads(ws, 64)
      await expect(ws.dispatch('read', '/m/leak.txt', [], { stream: true })).rejects.toMatchObject({
        code: 'EACCES',
      })
      expect(pulls.chunks).toBe(3)
      const clean = await chunksOf(await openStream(ws, '/m/plans.txt'))
      expect(clean.map((c) => DEC.decode(c))).toEqual(['y'.repeat(200)])
    } finally {
      await ws.close()
    }
  })

  it('keeps a result-blind post policy on the stream, whose deny closes it', async () => {
    const ws = ramWorkspace({ policies: [new BlindSeal()] })
    try {
      expect(ws.policies.readsResults()).toBe(false)
      await ws.vfs.writeFile('/m/a.sealed', pattern(1024))
      const pulls = chunkedReads(ws, 64)
      await expect(ws.dispatch('read', '/m/a.sealed', [], { stream: true })).rejects.toMatchObject({
        code: 'EACCES',
      })
      expect(pulls.chunks).toBe(1)
      expect(pulls.closed).toBe(true)
    } finally {
      await ws.close()
    }
  })

  it('settles the report with the moved bytes when the stream closes, not at open', async () => {
    const ws = ramWorkspace()
    try {
      await ws.vfs.writeFile('/m/big.bin', pattern(4 * 64))
      chunkedReads(ws, 64)
      const open = async (report: OpReport): Promise<ReadStream> => {
        const [stream] = (await doorOf(ws).dispatch(
          'read',
          PathSpec.fromStrPath('/m/big.bin'),
          [],
          { stream: true },
          report,
        )) as [ReadStream, unknown]
        return stream
      }
      const early = new OpReport()
      const partial = await open(early)
      expect(early.completed).toBe(false)
      await partial.next()
      await partial.next()
      expect(early.completed).toBe(false)
      await partial.return()
      expect([early.completed, early.bytes]).toEqual([true, 128])
      const full = new OpReport()
      const drained = await open(full)
      expect(full.completed).toBe(false)
      await chunksOf(drained)
      expect([full.completed, full.bytes]).toEqual([true, 256])
    } finally {
      await ws.close()
    }
  })

  it('refuses stream on an op other than read', async () => {
    const ws = ramWorkspace()
    try {
      await ws.vfs.writeFile('/m/a.txt', 'a')
      await expect(ws.dispatch('stat', '/m/a.txt', [], { stream: true })).rejects.toThrow(TypeError)
      await expect(
        ws.dispatch('write', '/m/a.txt', [ENC.encode('b')], { stream: true }),
      ).rejects.toThrow(TypeError)
      expect(DEC.decode((await ws.dispatch('read', '/m/a.txt')) as Uint8Array)).toBe('a')
    } finally {
      await ws.close()
    }
  })

  it('a lazy stream body sees the mount revision pins on its first pull', async () => {
    const ws = ramWorkspace()
    try {
      await ws.vfs.writeFile('/m/a.txt', 'a')
      const inner = ramReadOp(ws).stream
      const seen: (string | null)[] = []
      streamRead(ws, (accessor, path, args, kwargs) =>
        (async function* (): AsyncGenerator<Uint8Array> {
          seen.push(revisionFor(path.virtual))
          yield* inner(accessor, path, args, kwargs) as AsyncIterable<Uint8Array>
          seen.push(revisionFor(path.virtual))
        })(),
      )
      ws.namespace.mountFor('/m/a.txt').revisions.set('/m/a.txt', 'v1')
      const stream = await openStream(ws, '/m/a.txt')
      expect(revisionFor('/m/a.txt')).toBeNull()
      expect(DEC.decode(joined(await chunksOf(stream)))).toBe('a')
      expect(seen).toEqual(['v1', 'v1'])
    } finally {
      await ws.close()
    }
  })

  it('holds each pull to the read timeout from the mount command limits', async () => {
    const ws = ramWorkspace({ limits: { read: new Limit({ timeoutSeconds: 0.05 }) } })
    try {
      await ws.vfs.writeFile('/m/a.txt', 'a')
      const slowAt = { pull: 2 }
      streamRead(ws, () =>
        (async function* (): AsyncGenerator<Uint8Array> {
          for (let pull = 1; pull <= 3; pull++) {
            if (pull === slowAt.pull) await new Promise((resolve) => setTimeout(resolve, 300))
            yield ENC.encode(String(pull))
          }
        })(),
      )
      const stream = await openStream(ws, '/m/a.txt')
      expect(DEC.decode((await stream.next()).value as Uint8Array)).toBe('1')
      await expect(stream.next()).rejects.toThrow(CommandTimeoutError)
      slowAt.pull = 1
      await expect(ws.dispatch('read', '/m/a.txt', [], { stream: true })).rejects.toThrow(
        CommandTimeoutError,
      )
      expect(await settlesWithin(ws.unmount('/m'), 2000)).toBe(true)
    } finally {
      await ws.close()
    }
  })

  it.skipIf(collectGarbage === undefined)(
    'a stream dropped unclosed lets unmount complete once collected (needs a gc the runtime exposes)',
    async () => {
      const ws = ramWorkspace()
      try {
        await ws.vfs.writeFile('/m/big.bin', pattern(4 * 64))
        chunkedReads(ws, 64)
        const openAndDrop = async (): Promise<void> => {
          const stream = await openStream(ws, '/m/big.bin')
          expect(((await stream.next()).value as Uint8Array).byteLength).toBe(64)
        }
        await openAndDrop()
        let unmounted = false
        const unmounting = ws.unmount('/m').then(() => {
          unmounted = true
        })
        await new Promise((resolve) => setTimeout(resolve, 20))
        expect(unmounted).toBe(false)
        expect(await collectedWithin(() => unmounted)).toBe(true)
        await unmounting
      } finally {
        await ws.close()
      }
    },
  )
})

async function openReported(ws: Workspace, path: string, report: OpReport): Promise<ReadStream> {
  const [stream] = (await doorOf(ws).dispatch(
    'read',
    PathSpec.fromStrPath(path),
    [],
    { stream: true },
    report,
  )) as [ReadStream, unknown]
  expect(stream).toBeInstanceOf(ReadStream)
  return stream
}

describe('a streamed read collected unclosed', () => {
  it.skipIf(collectGarbage === undefined)(
    'settles its report with the moved bytes once collected (needs a gc the runtime exposes)',
    async () => {
      const ws = ramWorkspace()
      try {
        await ws.vfs.writeFile('/m/big.bin', pattern(4 * 64))
        chunkedReads(ws, 64)
        const report = new OpReport()
        const openAndDrop = async (): Promise<void> => {
          const stream = await openReported(ws, '/m/big.bin', report)
          expect(((await stream.next()).value as Uint8Array).byteLength).toBe(64)
          expect(((await stream.next()).value as Uint8Array).byteLength).toBe(64)
        }
        await openAndDrop()
        expect(report.completed).toBe(false)
        expect(await collectedWithin(() => report.completed)).toBe(true)
        expect(report.bytes).toBe(128)
      } finally {
        await ws.close()
      }
    },
  )

  it.skipIf(collectGarbage === undefined)(
    'closes the backend before an unmount closes the VFS once collected (needs a gc the runtime exposes)',
    async () => {
      const ram = new RAMVFS()
      const ws = ramWorkspace({ ram })
      try {
        await ws.vfs.writeFile('/m/big.bin', pattern(4 * 64))
        const pulls = chunkedReads(ws, 64)
        const backendClosedAtVfsClose: boolean[] = []
        const close = ram.close.bind(ram)
        vi.spyOn(ram, 'close').mockImplementation(() => {
          backendClosedAtVfsClose.push(pulls.closed)
          return close()
        })
        const openAndDrop = async (): Promise<void> => {
          const stream = await openStream(ws, '/m/big.bin')
          expect(((await stream.next()).value as Uint8Array).byteLength).toBe(64)
        }
        await openAndDrop()
        let unmounted = false
        const unmounting = ws.unmount('/m').then(() => {
          unmounted = true
        })
        await new Promise((resolve) => setTimeout(resolve, 20))
        expect(unmounted).toBe(false)
        expect(pulls.closed).toBe(false)
        expect(await collectedWithin(() => unmounted)).toBe(true)
        await unmounting
        expect(pulls.closed).toBe(true)
        expect(backendClosedAtVfsClose).toEqual([true])
      } finally {
        await ws.close()
      }
    },
  )
})

describe('a streamed read the op hands in a cache tee', () => {
  function teedReads(ws: Workspace, size: number): [Pulls, CachableAsyncIterator[]] {
    const pulls = chunkedReads(ws, size)
    const chunked = ramReadOp(ws).stream
    const tees: CachableAsyncIterator[] = []
    streamRead(ws, (accessor, path, args, kwargs) => {
      const tee = new CachableAsyncIterator(
        chunked(accessor, path, args, kwargs) as AsyncIterable<Uint8Array>,
      )
      tees.push(tee)
      return tee
    })
    return [pulls, tees]
  }

  it('closes the backend through the tee source on an early return, and unmount completes', async () => {
    const ws = ramWorkspace()
    try {
      await ws.vfs.writeFile('/m/big.bin', pattern(MIB))
      const [pulls, tees] = teedReads(ws, CHUNK)
      const report = new OpReport()
      const stream = await openReported(ws, '/m/big.bin', report)
      expect(((await stream.next()).value as Uint8Array).byteLength).toBe(CHUNK)
      await stream.return()
      expect(tees.length).toBe(1)
      expect(pulls.chunks).toBeLessThanOrEqual(2)
      expect(pulls.closed).toBe(true)
      expect(tees[0]?.bufferedChunks.length).toBe(0)
      expect([report.completed, report.bytes]).toEqual([true, CHUNK])
      expect(await settlesWithin(ws.unmount('/m'), 2000)).toBe(true)
    } finally {
      await ws.close()
    }
  })

  it('streams a drained read through the tee source without buffering it in the tee', async () => {
    const ws = ramWorkspace()
    try {
      const data = pattern(5 * CHUNK + 17)
      await ws.vfs.writeFile('/m/big.bin', data)
      const [pulls, tees] = teedReads(ws, CHUNK)
      const chunks = await chunksOf(await openStream(ws, '/m/big.bin'))
      expect(chunks.length).toBe(6)
      expect(joined(chunks)).toEqual(data)
      expect(pulls.closed).toBe(true)
      expect(tees[0]?.bufferedChunks.length).toBe(0)
      expect(await settlesWithin(ws.unmount('/m'), 2000)).toBe(true)
    } finally {
      await ws.close()
    }
  })
})

describe('shell streams over a device mount', () => {
  it.skipIf(collectGarbage === undefined)(
    'repeated /dev pipelines leave no stream held (needs a gc the runtime exposes)',
    async () => {
      const parser = await getTestParser()
      const ws = new Workspace(
        { '/data': new RAMVFS() },
        { mode: MountMode.WRITE, shellParserFactory: () => Promise.resolve(parser) },
      )
      try {
        for (let run = 0; run < 5; run++) {
          const result = await ws.shell('cat /dev/zero | head -c 4')
          expect(result.stdoutText).toBe('\0'.repeat(4))
        }
        const dev = ws.mounts().find((m) => m.prefix === '/dev/')
        if (dev === undefined) throw new Error('no /dev mount')
        let idle = false
        void dev.activity.wait().then(() => {
          idle = true
        })
        expect(await collectedWithin(() => idle)).toBe(true)
      } finally {
        await ws.close()
      }
    },
    30_000,
  )
})
