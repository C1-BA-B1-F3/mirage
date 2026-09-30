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

export const COMPOUND_EXTENSIONS: ReadonlySet<string> = new Set([
  '.gdoc.json',
  '.gslide.json',
  '.gsheet.json',
  '.gmail.json',
])

export function getExtension(path: string | null): string | null {
  if (path === null) return null
  const basename = path.split('/').pop() ?? ''
  for (const ext of COMPOUND_EXTENSIONS) {
    if (basename.endsWith(ext)) return ext
  }
  const dot = path.lastIndexOf('.')
  if (dot === -1 || path.slice(dot).includes('/')) return null
  return path.slice(dot)
}
