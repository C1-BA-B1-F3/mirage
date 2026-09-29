import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { describe, expect, it, vi } from 'vitest'
import { IOResult, materialize } from '../../../io/types.ts'
import { RAMVFS } from '../../../vfs/ram/ram.ts'
import { createShellParser } from '../../../shell/parse/index.ts'
import { Workspace } from '../../../workspace/workspace/workspace.ts'
import { FileStat, FileType, MountMode, PathSpec } from '../../../types.ts'
import type { DispatchFn } from '../../../runtime/types.ts'
import { eisdir, enoent, enotdir } from '../../../utils/errors.ts'
import { prepareProgram, programFileRefusal, readProgramFile } from './program.ts'

const require = createRequire(import.meta.url)
const engineWasm = readFileSync(require.resolve('web-tree-sitter/web-tree-sitter.wasm'))
const grammarWasm = readFileSync(require.resolve('tree-sitter-bash/tree-sitter-bash.wasm'))
const corpus = JSON.parse(
  readFileSync(
    new URL('../../../../../../../integ/crossmount/program/files.json', import.meta.url),
    'utf8',
  ),
) as {
  cases: { id: string; command: string; expect: { exit: number; stdout: string; stderr: string } }[]
}

describe('program file routing', () => {
  it.each([
    ['grep', '-rn pattern', ['-rn', 'pattern']],
    ['sed', '-n p', ['-n', 'p']],
    ['awk', '-F : program', ['-F', ':', 'program']],
    ['jq', '-r .a', ['-r', '.a']],
  ])('leaves inline %s arguments to the mount spec', async (name, args, texts) => {
    const ws = new Workspace(
      { '/data': new RAMVFS() },
      {
        mode: MountMode.EXEC,
        shellParserFactory: async () => createShellParser({ engineWasm, grammarWasm }),
      },
    )
    try {
      const mount = ws.registry.mountFor('/data')
      vi.spyOn(mount, 'specFor').mockReturnValue(null)
      const execute = vi.spyOn(mount, 'executeCmd').mockResolvedValue([null, new IOResult()])
      const result = await ws.shell(`${name} ${args} /data/input`)
      expect(result.exitCode).toBe(0)
      expect(execute).toHaveBeenCalledOnce()
      expect(execute.mock.calls[0]?.[2]).toEqual(texts)
      expect(execute.mock.calls[0]?.[3]).toEqual({})
    } finally {
      await ws.close()
    }
  })

  for (const test of corpus.cases) {
    it(test.id, async () => {
      const ws = new Workspace(
        { '/data': new RAMVFS(), '/data2': new RAMVFS() },
        {
          mode: MountMode.EXEC,
          shellParserFactory: async () => createShellParser({ engineWasm, grammarWasm }),
        },
      )
      try {
        const result = await ws.shell(test.command)
        const dec = new TextDecoder()
        expect({
          exit: result.exitCode,
          stdout: dec.decode(result.stdout),
          stderr: dec.decode(result.stderr),
        }).toEqual(test.expect)
      } finally {
        await ws.close()
      }
    })
  }
})

function typed(raw: string): PathSpec {
  const virtual = raw.startsWith('/') ? raw : `/${raw}`
  return new PathSpec({ virtual, directory: '/', vfsPath: '', resolved: true, rawPath: raw })
}

const noDispatch = ((op: string, path: PathSpec) => {
  throw new Error(`stdin only, but ${op} ${path.virtual} was dispatched`)
}) as unknown as DispatchFn

const ENC = new TextEncoder()
const DEC = new TextDecoder()

describe('rg program files from stdin', () => {
  it('lowers a -f - to --regexp', async () => {
    const [texts, flags, rest, error] = await prepareProgram(
      'rg',
      ['/in'],
      { file: [typed('-')] },
      ENC.encode('a\nb\n'),
      noDispatch,
    )
    expect(error).toBeNull()
    expect([texts, flags]).toEqual([['/in'], { file: [], regexp: ['a\nb'] }])
    expect(await materialize(rest)).toEqual(new Uint8Array())
  })

  it('refuses a second -f -', async () => {
    // ripgrep 14.1.1: `rg -f - -f -` reads stdin once and refuses the second
    // before any operand is looked at.
    const [, , , error] = await prepareProgram(
      'rg',
      [],
      { file: [typed('-'), typed('-')] },
      ENC.encode('a\n'),
      noDispatch,
      [typed('-')],
    )
    expect(error?.exitCode).toBe(2)
    expect(DEC.decode(error?.stderr as Uint8Array)).toBe(
      'rg: error reading -f/--file from stdin: stdin has already been consumed\n',
    )
  })

  it('refuses a - operand after -f -', async () => {
    const [, , , error] = await prepareProgram(
      'rg',
      [],
      { file: [typed('-')] },
      ENC.encode('a\n'),
      noDispatch,
      [typed('/in'), typed('-')],
    )
    expect(error?.exitCode).toBe(2)
    expect(DEC.decode(error?.stderr as Uint8Array)).toBe(
      'rg: error: attempted to read patterns from stdin while also searching stdin\n',
    )
  })

  it('takes no - from -f /dev/stdin', async () => {
    // ripgrep reads `-f /dev/stdin` as a file, so a `-` operand after it
    // searches what is left of stdin (nothing) rather than being refused.
    const [, flags, rest, error] = await prepareProgram(
      'rg',
      [],
      { file: [typed('/dev/stdin')] },
      ENC.encode('a\n'),
      noDispatch,
      [typed('-')],
    )
    expect(error).toBeNull()
    expect(flags).toEqual({ file: [], regexp: ['a'] })
    expect(await materialize(rest)).toEqual(new Uint8Array())
  })

  it('leaves grep reading a second -f - as empty', async () => {
    // GNU grep 3.11 reads the second `-f -` as an empty pattern file.
    const [, flags, , error] = await prepareProgram(
      'grep',
      [],
      { file: [typed('-'), typed('-')], e: [] },
      ENC.encode('a\n'),
      noDispatch,
      [typed('-')],
    )
    expect(error).toBeNull()
    expect(flags).toEqual({ file: [], e: ['a'] })
  })
})

describe('a program file the command cannot read', () => {
  // grep 3.11, ripgrep 14.1.1, gzip 1.13 (zgrep copies the file with cat),
  // sed 4.9, mawk 1.3.4, jq 1.7.1 on debian:stable-slim. Mirrors python's
  // test_a_program_file_refusal_is_in_each_commands_words.
  it.each([
    ['grep', eisdir('/dir'), 'grep: dir: Is a directory\n', 2],
    ['grep', enoent('/dir'), 'grep: dir: No such file or directory\n', 2],
    ['rg', eisdir('/dir'), 'rg: dir:Is a directory (os error 21)\n', 2],
    ['rg', enoent('/dir'), 'rg: dir: No such file or directory (os error 2)\n', 2],
    ['rg', enotdir('/dir'), 'rg: dir: Not a directory (os error 20)\n', 2],
    ['zgrep', eisdir('/dir'), 'cat: dir: Is a directory\n', 2],
    ['zgrep', enoent('/dir'), 'cat: dir: No such file or directory\n', 2],
    ['sed', enoent('/dir'), "sed: couldn't open file dir: No such file or directory\n", 4],
    ['awk', eisdir('/dir'), 'awk: read error (Is a directory)\n', 2],
    ['awk', enoent('/dir'), 'awk: cannot open "dir" (No such file or directory)\n', 2],
    ['jq', eisdir('/dir'), "jq: Could not open dir: It's a directory\n", 2],
    ['jq', enoent('/dir'), 'jq: Could not open dir: No such file or directory\n', 2],
  ] as const)('%s words %s its own way', (name, err, line, code) => {
    expect(programFileRefusal(name, typed('dir'), err)).toEqual([line, code])
  })

  it.each([
    ['sed', true],
    ['grep', false],
  ])('reads a directory as %s reads it', async (name, empty) => {
    // sed 4.9 reads a directory as an empty script; everyone else fails its
    // read, which the stat tells from a keyed store's plain miss.
    const dispatch: DispatchFn = (op, path) => {
      if (op !== 'stat') throw new Error(`${op} ${path.virtual} was dispatched`)
      return Promise.resolve([
        new FileStat({ name: 'dir', type: FileType.DIRECTORY }),
        new IOResult(),
      ])
    }
    const read = readProgramFile(name, typed('dir'), dispatch)
    if (empty) expect((await read).byteLength).toBe(0)
    else await expect(read).rejects.toMatchObject({ code: 'EISDIR' })
  })
})
