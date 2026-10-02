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

interface NodeFs {
  readFile(path: string): Promise<Uint8Array>
  writeFile(path: string, data: Uint8Array): Promise<void>
}

async function tryLoadFs(): Promise<NodeFs | null> {
  const g = globalThis as unknown as { process?: { versions?: { node?: string } } }
  if (g.process?.versions?.node === undefined) return null
  try {
    const modName = 'node:fs/promises'
    const mod = (await import(/* @vite-ignore */ modName)) as NodeFs
    return mod
  } catch {
    return null
  }
}

const nodeFs: NodeFs | null = await tryLoadFs()

export async function readFileBytes(path: string): Promise<Uint8Array> {
  if (nodeFs === null) throw new Error('readFileBytes: not available (node:fs unavailable)')
  return nodeFs.readFile(path)
}

export async function writeFileBytes(path: string, data: Uint8Array): Promise<void> {
  if (nodeFs === null) throw new Error('writeFileBytes: not available (node:fs unavailable)')
  await nodeFs.writeFile(path, data)
}
