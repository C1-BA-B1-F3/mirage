import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { beforeAll, expect, it } from 'vitest'

import { createShellParser, type ShellParser } from '../../../../shell/parse/index.ts'
import { Workspace } from '../../../../workspace/workspace/workspace.ts'
import { VERSION } from '../../../../version.ts'
import { GH } from './index.ts'

const require = createRequire(import.meta.url)
let parser: ShellParser

beforeAll(async () => {
  parser = await createShellParser({
    engineWasm: readFileSync(require.resolve('web-tree-sitter/web-tree-sitter.wasm')),
    grammarWasm: readFileSync(require.resolve('tree-sitter-bash/tree-sitter-bash.wasm')),
  })
})

it.each(['version', '--version'])(
  'reports the version without a mount or API: %s',
  async (form) => {
    const ws = new Workspace({}, { shellParser: parser })
    ws.registerCli('gh', GH, { token: 'unused', base_url: 'http://127.0.0.1:1' })
    try {
      const result = await ws.shell(`gh ${form}`)
      expect(result.exitCode).toBe(0)
      expect(new TextDecoder().decode(result.stdout)).toBe(`gh version ${VERSION} (Mirage)\n`)
      expect(result.stderr).toHaveLength(0)
    } finally {
      await ws.close()
    }
  },
)
