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

import type { ContextCall } from './async_context.ts'

/** Replay captured storage frames around callbacks, including async continuations. */
export class ContextScope {
  constructor(private readonly scopes: readonly ContextCall[]) {}

  call<T>(fn: () => T): T {
    const enter = (at: number): T => {
      const scope = this.scopes[at]
      return scope === undefined ? fn() : (scope(() => enter(at + 1)) as T)
    }
    return enter(0)
  }

  async run<T>(fn: () => Promise<T>): Promise<T> {
    return await this.call(fn)
  }

  wrap<A extends unknown[], R>(fn: (...args: A) => R): (...args: A) => R {
    return (...args) => this.call(() => fn(...args))
  }
  async *stream<T>(source: AsyncIterable<T>): AsyncGenerator<T> {
    const iterator = source[Symbol.asyncIterator]()
    try {
      for (;;) {
        const next = await this.run(() => iterator.next())
        if (next.done === true) return
        yield next.value
      }
    } finally {
      const finish = iterator.return?.bind(iterator)
      if (finish !== undefined) await this.run(finish)
    }
  }
}
