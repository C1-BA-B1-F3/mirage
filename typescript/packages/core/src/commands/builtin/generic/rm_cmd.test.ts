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

import { execFile } from 'node:child_process'
import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'
import { promisify } from 'node:util'
import { it } from 'vitest'

it('loads rm first under native ESM without the Vitest module runner', async () => {
  const compiler = pathToFileURL(createRequire(import.meta.url).resolve('typescript')).href
  const loader = `
    import { readFile } from 'node:fs/promises';
    import ts from ${JSON.stringify(compiler)};
    export async function load(url, context, nextLoad) {
      if (url.endsWith('.ts') && !url.includes('/node_modules/')) {
        const source = ts.transpileModule(await readFile(new URL(url), 'utf8'), {
          compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext }
        }).outputText;
        return { format: 'module', source, shortCircuit: true };
      }
      return nextLoad(url, context);
    }
  `
  const target = new URL('./rm_cmd.ts', import.meta.url).href
  await promisify(execFile)(
    process.execPath,
    [
      '--loader',
      `data:text/javascript,${encodeURIComponent(loader)}`,
      '--input-type=module',
      '-e',
      `await import(${JSON.stringify(target)})`,
    ],
    { timeout: 15000 },
  )
})
