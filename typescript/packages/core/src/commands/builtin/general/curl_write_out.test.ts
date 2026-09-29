import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { afterEach, beforeAll, expect, it, vi } from 'vitest'
import { createShellParser, type ShellParser } from '../../../shell/parse/index.ts'
import { GENERAL_CURL } from './curl.ts'
import { eacces, enoent } from '../../../utils/errors.ts'
import { RAMVFS } from '../../../vfs/ram/ram.ts'
import { MountMode } from '../../../types.ts'
import { Workspace } from '../../../workspace/workspace/workspace.ts'

const require = createRequire(import.meta.url)
let parser: ShellParser
beforeAll(async () => {
  parser = await createShellParser({
    engineWasm: readFileSync(require.resolve('web-tree-sitter/web-tree-sitter.wasm')),
    grammarWasm: readFileSync(require.resolve('tree-sitter-bash/tree-sitter-bash.wasm')),
  })
})
afterEach(() => vi.unstubAllGlobals())
interface Case {
  id: string
  command: string
  expect: { exit: number; stdout: string; stderr: string }
}
const cases = (
  JSON.parse(
    readFileSync(
      new URL('../../../../../../../integ/vfs/http/curl_write_out.json', import.meta.url),
      'utf8',
    ),
  ) as { cases: Case[] }
).cases
it.each(cases)('$id', async (row) => {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: string) => {
      if (input.includes(':9/')) return Promise.reject(new TypeError('fetch failed'))
      return Promise.resolve(
        new Response(input.endsWith('/missing') ? 'not found\n' : 'hello from http\n', {
          status: input.endsWith('/missing') ? 404 : 200,
          headers: { 'content-type': 'text/plain' },
        }),
      )
    }),
  )
  const ws = new Workspace({ '/data': new RAMVFS() }, { mode: MountMode.EXEC, shellParser: parser })
  try {
    const result = await ws.shell(
      row.command.replaceAll('{mount}', '/data').replaceAll('{http}', 'https://example.test'),
    )
    expect(result.exitCode).toBe(row.expect.exit)
    expect(new TextDecoder().decode(result.stdout)).toBe(row.expect.stdout)
    expect(new TextDecoder().decode(result.stderr)).toBe(
      row.expect.stderr.replaceAll('{mount}', '/data'),
    )
  } finally {
    await ws.close()
  }
})
it('wget enforces its deadline and returns the network failure code', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(
      (_input: string, init: RequestInit) =>
        new Promise((_resolve, reject) => {
          if (init.signal == null) throw new Error('request lacks a timeout signal')
          init.signal.addEventListener('abort', () => {
            reject(new DOMException('aborted', 'AbortError'))
          })
        }),
    ),
  )
  const ws = new Workspace({}, { shellParser: parser })
  try {
    const result = await ws.shell('wget --timeout=0.01 -q -O - https://example.test/hello')
    expect(result.exitCode).toBe(4)
    expect(result.stderr.length).toBe(0)
  } finally {
    await ws.close()
  }
})

it.each([undefined, enoent('/format'), eacces('/format')])(
  'refuses a transfer when its template cannot be read (%s)',
  async (failure) => {
    const request = vi.fn()
    vi.stubGlobal('fetch', request)
    const cmd = GENERAL_CURL[0]
    if (cmd === undefined) throw new Error('curl not registered')
    for (const [silent, show_error] of [
      [false, false],
      [true, false],
      [true, true],
    ]) {
      const detail = silent ? '' : 'curl: Failed to open /format\n'
      await expect(
        cmd.fn(new RAMVFS().accessor, [], ['https://example.test/hello'], {
          stdin: null,
          cwd: '/',
          filetypeFns: null,
          flags: {
            write_out: '@/format',
            silent: silent ?? false,
            show_error: show_error ?? false,
          },
          ...(failure === undefined ? {} : { dispatch: vi.fn().mockRejectedValue(failure) }),
        }),
      ).rejects.toMatchObject({
        exitCode: 26,
        message:
          detail +
          'curl: option -w: error encountered when reading a file\n' +
          "curl: try 'curl --help' or 'curl --manual' for more information",
      })
    }
    expect(request).not.toHaveBeenCalled()
  },
)
