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

/** A full entry path under `dir`, whatever shape the listing spelled. */
function joinEntry(dir: string, name: string): string {
  const clean = name.endsWith('/') ? name.slice(0, -1) : name
  if (clean.startsWith('/')) return clean
  return dir === '/' ? '/' + clean : dir + '/' + clean
}

/** Sort paths the way python sorts PurePosixPath: by parts, not raw bytes. */
function sortPaths(paths: string[]): string[] {
  return paths
    .map((p): [string[], string] => [p.split('/'), p])
    .sort((a, b) => {
      const [pa] = a
      const [pb] = b
      const n = Math.min(pa.length, pb.length)
      for (let i = 0; i < n; i++) {
        const x = pa[i] ?? ''
        const y = pb[i] ?? ''
        if (x !== y) return x < y ? -1 : 1
      }
      return pa.length - pb.length
    })
    .map(([, p]) => p)
}

/**
 * A listing's entries as the guest's paths, sorted as pathlib sorts.
 * Backends spell entries differently (bare names, slash-marked
 * directories, full paths); joining each onto the directory takes all
 * three to one path.
 */
export function childPaths(path: string, names: string[]): string[] {
  return sortPaths([...new Set(names.map((name) => joinEntry(path, name)))])
}
