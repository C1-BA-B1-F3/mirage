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

/**
 * A thrown value, told the way a command can print it. Most guest
 * failures are Errors, but Emscripten and a crashed worker can surface a
 * plain object, whose String() is `[object Object]`: its name and message
 * say more, and failing those its keys.
 */
export function failureText(value: unknown): string {
  if (value instanceof Error) return value.message
  if (typeof value !== 'object' || value === null) return String(value)
  const { name, message } = value as { name?: unknown; message?: unknown }
  const said = [name, message].filter((part) => typeof part === 'string' && part !== '')
  if (said.length > 0) return said.join(': ')
  const keys = Object.keys(value).join(', ')
  return `an object with keys: ${keys !== '' ? keys : '(none)'}`
}
