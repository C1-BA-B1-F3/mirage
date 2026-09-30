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

import type { Tree } from './store.ts'

// Linguist's names and types for the files a fixture holds, by extension or,
// for a file its name alone identifies, by name. Only programming and markup
// count towards a repository's languages, as on GitHub; data and prose are a
// file's language for code search and nothing more.
type Kind = 'programming' | 'markup' | 'data' | 'prose'

const BY_EXTENSION: Record<string, [string, Kind]> = {
  py: ['Python', 'programming'],
  pyi: ['Python', 'programming'],
  ts: ['TypeScript', 'programming'],
  mts: ['TypeScript', 'programming'],
  cts: ['TypeScript', 'programming'],
  tsx: ['TSX', 'programming'],
  js: ['JavaScript', 'programming'],
  mjs: ['JavaScript', 'programming'],
  cjs: ['JavaScript', 'programming'],
  jsx: ['JavaScript', 'programming'],
  go: ['Go', 'programming'],
  rs: ['Rust', 'programming'],
  java: ['Java', 'programming'],
  kt: ['Kotlin', 'programming'],
  c: ['C', 'programming'],
  h: ['C', 'programming'],
  cc: ['C++', 'programming'],
  cpp: ['C++', 'programming'],
  cxx: ['C++', 'programming'],
  hpp: ['C++', 'programming'],
  cs: ['C#', 'programming'],
  rb: ['Ruby', 'programming'],
  php: ['PHP', 'programming'],
  swift: ['Swift', 'programming'],
  scala: ['Scala', 'programming'],
  hs: ['Haskell', 'programming'],
  lua: ['Lua', 'programming'],
  r: ['R', 'programming'],
  pl: ['Perl', 'programming'],
  dart: ['Dart', 'programming'],
  ex: ['Elixir', 'programming'],
  exs: ['Elixir', 'programming'],
  sh: ['Shell', 'programming'],
  bash: ['Shell', 'programming'],
  ps1: ['PowerShell', 'programming'],
  html: ['HTML', 'markup'],
  htm: ['HTML', 'markup'],
  css: ['CSS', 'markup'],
  scss: ['SCSS', 'markup'],
  vue: ['Vue', 'markup'],
  ipynb: ['Jupyter Notebook', 'markup'],
  json: ['JSON', 'data'],
  yml: ['YAML', 'data'],
  yaml: ['YAML', 'data'],
  toml: ['TOML', 'data'],
  xml: ['XML', 'data'],
  csv: ['CSV', 'data'],
  sql: ['SQL', 'data'],
  md: ['Markdown', 'prose'],
  rst: ['reStructuredText', 'prose'],
  txt: ['Text', 'prose'],
}

const BY_NAME: Record<string, [string, Kind]> = {
  Dockerfile: ['Dockerfile', 'programming'],
  Makefile: ['Makefile', 'programming'],
}

// Linguist leaves out what a repository vendors and what documents it.
const LEFT_OUT = /(?:^|\/)(?:node_modules|vendor|third_party|docs?|Documentation)\//

function kindOf(path: string): [string, Kind] | null {
  const name = path.slice(path.lastIndexOf('/') + 1)
  const named = BY_NAME[name]
  if (named !== undefined) return named
  const dot = name.lastIndexOf('.')
  return dot <= 0 ? null : (BY_EXTENSION[name.slice(dot + 1).toLowerCase()] ?? null)
}

/** A file's language, as code search's `language:` reads it, or null. */
export function languageOf(path: string): string | null {
  return kindOf(path)?.[0] ?? null
}

/**
 * The bytes of each language a tree holds, largest first, as
 * `GET /repos/{owner}/{repo}/languages` reports them.
 */
export function languagesOf(files: Tree): Array<[string, number]> {
  const sizes = new Map<string, number>()
  for (const [path, data] of files) {
    const kind = kindOf(path)
    if (kind === null || LEFT_OUT.test(path)) continue
    if (kind[1] !== 'programming' && kind[1] !== 'markup') continue
    sizes.set(kind[0], (sizes.get(kind[0]) ?? 0) + data.length)
  }
  return [...sizes].sort(([a, x], [b, y]) => y - x || (a < b ? -1 : 1))
}
