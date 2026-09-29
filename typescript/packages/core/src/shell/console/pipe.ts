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

import { JobConsole } from './job_console.ts'
import { Channel } from './types.ts'
import { PipeClosed } from '../errors.ts'

/** A single-reader pipe with a kernel-sized buffer. A write succeeds while
 * the reader is open and the buffer has room, as in bash, where a producer
 * that finishes before `head` closes keeps its status. A lazy source is
 * pulled only after `drain`, so closing after one chunk does not fetch
 * another backend page first. */
export class PipeConsole extends JobConsole {
  private chunks: Uint8Array[] = []
  private bytes = 0
  private ended = false
  private readerClosed = false
  private delivered = 0
  private accepted = 0
  private failure: Error | undefined
  private wake: (() => void)[] = []

  constructor(private readonly pipeStderr = false) {
    super()
  }

  private notify(): void {
    for (const resolve of this.wake.splice(0)) resolve()
  }

  private changed(): Promise<void> {
    return new Promise((resolve) => this.wake.push(resolve))
  }

  override async emit(channel: Channel, data: Uint8Array): Promise<void> {
    if (channel !== Channel.STDOUT && !this.pipeStderr) {
      await super.emit(channel, data)
      return
    }
    if (data.byteLength === 0) return
    while (this.bytes >= 65536 && !this.readerClosed) await this.changed()
    if (this.readerClosed) throw new PipeClosed()
    this.chunks.push(data)
    this.bytes += data.byteLength
    this.delivered += 1
    this.notify()
  }

  /** Wait until the reader has taken every chunk or closed. */
  async drain(): Promise<void> {
    while (this.accepted < this.delivered && !this.readerClosed) await this.changed()
  }

  get closedReader(): boolean {
    return this.readerClosed
  }

  end(error?: unknown): void {
    if (error !== undefined)
      this.failure =
        error instanceof Error ? error : new Error('Pipeline producer failed', { cause: error })
    this.ended = true
    this.notify()
  }

  closeReader(): void {
    this.readerClosed = true
    this.chunks = []
    this.bytes = 0
    this.notify()
  }

  /** The reader is done. The close lands on the next task-queue turn, the
   * way a kernel pipe closes when its reader exits: a writer that is not
   * blocked finishes its burst into the buffer first, as it does on the
   * python host, whose reader runs only once the writer suspends. */
  release(): void {
    setTimeout(() => {
      this.closeReader()
    }, 0)
  }

  async *stream(): AsyncGenerator<Uint8Array> {
    try {
      for (;;) {
        const chunk = this.chunks.shift()
        if (chunk !== undefined) {
          this.bytes -= chunk.byteLength
          this.notify()
          yield chunk
          this.accepted += 1
          this.notify()
        } else if (this.ended) {
          if (this.failure !== undefined) throw this.failure
          return
        } else {
          await this.changed()
        }
      }
    } finally {
      this.release()
    }
  }
}
