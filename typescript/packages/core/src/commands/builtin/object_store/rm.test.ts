import { expect, it, vi } from 'vitest'
import { materialize } from '../../../io/types.ts'
import type { Accessor } from '../../../accessor/base.ts'
import { FileStat, FileType, PathSpec } from '../../../types.ts'
import { withPathGuards, type CommandIO } from '../generic_bind/adapter.ts'
import { makeRm } from './rm.ts'

it.each([
  ['ENOENT', '', 'No such file or directory'],
  ['ELOOP', 'loop/child', 'Too many levels of symbolic links'],
] as const)('rm handles refused %s operands and continues', async (refusal, raw, message) => {
  for (const force of [false, true]) {
    const stat = vi.fn(() => Promise.resolve(new FileStat({ name: 'ok', type: FileType.FILE })))
    const unlink = vi.fn(() => Promise.resolve())
    const io: CommandIO = {
      readdir: () => Promise.resolve([]),
      readBytes: () => Promise.resolve(new Uint8Array()),
      readStream: () => {
        throw new Error('unexpected read')
      },
      stat,
      unlink,
      rmdir: unlink,
      rmR: unlink,
      isMounted: () => true,
    }
    const command = makeRm('s3', withPathGuards(io))[0]
    if (command === undefined) throw new Error('rm was not registered')
    const refused = new PathSpec({
      virtual: '/data',
      directory: '/',
      vfsPath: 'data',
      rawPath: raw,
      walkError: refusal,
    })
    const valid = PathSpec.fromStrPath('/data/ok')
    const result = await command.fn({} as Accessor, [refused, valid], [], {
      flags: { f: force },
      stdin: null,
      filetypeFns: null,
      cwd: '/',
    })
    const ignored = force && refusal === 'ENOENT'
    expect(result?.[1].exitCode).toBe(ignored ? 0 : 1)
    expect(new TextDecoder().decode(await materialize(result?.[1].stderr ?? null))).toBe(
      ignored ? '' : `rm: cannot remove '${raw}': ${message}\n`,
    )
    expect(stat).toHaveBeenCalledTimes(1)
    expect(unlink.mock.calls).toHaveLength(1)
  }
})
