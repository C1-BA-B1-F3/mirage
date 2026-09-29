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

import type { RunArgs } from '../types.ts'

/** Bind the script-CLI contract before compiling the unmodified program. */
export function prepareSource(args: RunArgs): string {
  if (!args.scriptCli) return args.code
  // JSON string literals are also Python string literals; encode twice so
  // Python's JSON decoder, not its source parser, handles source escapes.
  const source = `__import__('json').loads(${JSON.stringify(JSON.stringify(args.code))})`
  const prog = JSON.stringify(args.prog ?? '-c')
  const stdin = args.stdin === null ? 'None' : "__import__('sys').stdin.buffer.read()"
  return [
    `__import__('sys').argv[0] = ${prog}`,
    "argv = list(__import__('sys').argv)",
    `stdin = ${stdin}`,
    "__import__('sys').stdin = __import__('io').TextIOWrapper(" +
      "__import__('io').BytesIO(stdin or b''), encoding=__import__('sys').stdin.encoding, " +
      "errors=__import__('sys').stdin.errors)",
    `exec(compile(${source}, ${prog}, 'exec'), globals())`,
  ].join('\n')
}
