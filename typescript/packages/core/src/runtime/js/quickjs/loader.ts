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

import type { QuickJSAsyncWASMModule } from 'quickjs-emscripten'
import { QuickJsUnavailableError } from './errors.ts'

export type NewAsyncModule = () => Promise<QuickJSAsyncWASMModule>

/** Import the optional engine package, failing loud when it is absent. */
export async function loadQuickJsModule(): Promise<NewAsyncModule> {
  try {
    const mod = (await import('quickjs-emscripten')) as unknown as {
      newQuickJSAsyncWASMModule: NewAsyncModule
    }
    return mod.newQuickJSAsyncWASMModule
  } catch (err) {
    throw new QuickJsUnavailableError(
      "the quickjs runtime requires the 'quickjs-emscripten' package — install it to run `node`/`js`",
      { cause: err },
    )
  }
}
