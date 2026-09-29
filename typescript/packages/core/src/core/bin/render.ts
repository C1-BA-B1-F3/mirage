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

import { shellQuote } from '../../utils/quote.ts'

/**
 * The body of one program's file: a script that runs the command. mirage
 * runs every program itself, so the file is not the program; it is where
 * PATH finds it, its one comment (`note`) says what runs the name, and
 * running it by path runs the command the name does (`command` skips a
 * shadowing function).
 */
export function renderStub(name: string, note: string): Uint8Array {
  return new TextEncoder().encode(`#!/bin/sh\n# ${note}\ncommand ${shellQuote(name)} "$@"\n`)
}
