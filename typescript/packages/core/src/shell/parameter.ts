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

import { PARAMETER_NAME } from './constants.ts'

/**
 * Recognize a plain dollar reference, returning its name and end.
 *
 * Names use Bash's ASCII identifier grammar. Unbraced positionals
 * consume one digit; braces permit multiple digits. Special parameters
 * consume one character. The caller owns quoting and must only scan a
 * live dollar. Complex braced operators remain the expansion parser's
 * responsibility and return null here, as do non-reference dollars.
 * `start` and the returned end are offsets into `text`.
 */
export function scanParameter(text: string, start: number): [string, number] | null {
  if (text[start] !== '$') return null
  let begin = start + 1
  const braced = text[begin] === '{'
  if (braced) begin += 1
  const match = PARAMETER_NAME.exec(text.slice(begin))
  if (match === null) return null
  let name = match[0]
  if (!braced && /^[0-9]/.test(name)) name = name.slice(0, 1)
  let end = begin + name.length
  if (braced) {
    if (text[end] !== '}') return null
    end += 1
  }
  return [name, end]
}
