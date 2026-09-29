import { execFileSync } from 'node:child_process'
import { mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync, unlinkSync } from 'node:fs'
import { createRequire } from 'node:module'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { beforeAll, expect, it } from 'vitest'
import { createShellParser, type ShellParser } from '../../../../shell/parse/index.ts'
import { RAMVFS } from '../../../../vfs/ram/ram.ts'
import { MountMode } from '../../../../types.ts'
import { Workspace } from '../../../../workspace/workspace/workspace.ts'
import { GIT } from './index.ts'

const require = createRequire(import.meta.url)
let parser: ShellParser
beforeAll(async () => {
  parser = await createShellParser({
    engineWasm: readFileSync(require.resolve('web-tree-sitter/web-tree-sitter.wasm')),
    grammarWasm: readFileSync(require.resolve('tree-sitter-bash/tree-sitter-bash.wasm')),
  })
})
function workspace(): Workspace {
  const ws = new Workspace(
    { '/repo': new RAMVFS() },
    { mode: MountMode.WRITE, shellParser: parser },
  )
  ws.registerCli('git', GIT)
  return ws
}
async function load(ws: Workspace, root: string, relative = ''): Promise<void> {
  for (const entry of readdirSync(join(root, relative), { withFileTypes: true })) {
    const name = relative ? `${relative}/${entry.name}` : entry.name
    if (entry.isDirectory()) {
      await ws.shell(`mkdir -p /repo/${name}`)
      await load(ws, root, name)
    } else await ws.dispatch('write', `/repo/${name}`, [readFileSync(join(root, name))])
  }
}
function native(root: string, args: string[]): string {
  return execFileSync(
    'git',
    ['-C', root, '-c', 'user.name=Test', '-c', 'user.email=test@example.com', ...args],
    { encoding: 'utf8' },
  )
}
it('initializes, reinitializes safely, and inspects empty repositories', async () => {
  const ws = workspace()
  try {
    for (const command of [
      'mkdir -p /repo/project/.git',
      'git init -q -b main /repo/project',
      'git -C /repo/project stash list',
      'git init -q /repo/project',
    ]) {
      const result = await ws.shell(command)
      expect(new TextDecoder().decode(result.stderr)).toBe('')
      expect(result.exitCode).toBe(0)
    }
    expect(new TextDecoder().decode((await ws.shell('cat /repo/project/.git/HEAD')).stdout)).toBe(
      'ref: refs/heads/main\n',
    )
    const result = await ws.shell('git -C /repo/project fsck')
    expect(result.exitCode).toBe(0)
    expect(new TextDecoder().decode(result.stderr)).toBe(
      'notice: HEAD points to an unborn branch (main)\nnotice: No default references\n',
    )
    expect((await ws.shell('git -C /repo/project stash show')).exitCode).toBe(1)
    expect((await ws.shell('git help')).stdout).toEqual((await ws.shell('git --help')).stdout)
    expect((await ws.shell('git help status')).stdout).toEqual(
      (await ws.shell('git status --help')).stdout,
    )
  } finally {
    await ws.close()
  }
})
it.each([false, true])(
  'checks native objects and reads native stashes (packed=%s)',
  async (packed) => {
    const root = mkdtempSync(join(tmpdir(), 'mirage-1330-'))
    let ws = workspace()
    try {
      native(root, ['init', '-q', '-b', 'main'])
      writeFileSync(join(root, 'a.txt'), 'before\n')
      native(root, ['add', '.'])
      native(root, ['commit', '-qm', 'first'])
      writeFileSync(join(root, 'a.txt'), 'before\nafter\n')
      native(root, ['stash', 'push', '-m', 'saved'])
      if (packed) native(root, ['gc', '--prune=now'])
      await load(ws, root)
      const checked = await ws.shell('git -C /repo fsck --no-dangling')
      expect(new TextDecoder().decode(checked.stderr)).toBe('')
      expect(checked.exitCode).toBe(0)
      for (const args of [
        ['stash', 'list'],
        ['stash', 'show'],
        ['stash', 'show', '-p'],
        ['stash', 'show', '--name-only', 'stash@{0}'],
      ]) {
        const result = await ws.shell('git -C /repo ' + args.join(' '))
        expect(new TextDecoder().decode(result.stderr)).toBe('')
        expect(result.exitCode).toBe(0)
        expect(new TextDecoder().decode(result.stdout)).toBe(native(root, args))
      }
      if (!packed) {
        const oid = native(root, ['rev-parse', 'HEAD:a.txt']).trim()
        unlinkSync(join(root, '.git/objects', oid.slice(0, 2), oid.slice(2)))
        await ws.close()
        ws = workspace()
        await load(ws, root)
        const broken = await ws.shell('git -C /repo fsck --no-dangling')
        expect(broken.exitCode).not.toBe(0)
        expect(new TextDecoder().decode(broken.stderr)).toContain(oid)
      }
    } finally {
      await ws.close()
      rmSync(root, { recursive: true, force: true })
    }
  },
)
