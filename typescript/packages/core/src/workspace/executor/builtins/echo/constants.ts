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

export const SIMPLE_ESCAPES: Readonly<Record<string, string>> = Object.freeze({
  '\\': '\\',
  n: '\n',
  t: '\t',
  r: '\r',
  a: '\x07',
  b: '\b',
  f: '\f',
  v: '\v',
  e: '\x1b',
  E: '\x1b',
})

export const HEX_ESCAPE_DIGITS: Readonly<Record<string, number>> = Object.freeze({
  x: 2,
  u: 4,
  U: 8,
})

export const HEX = new Set('0123456789abcdefABCDEF')
export const OCT = new Set('01234567')
