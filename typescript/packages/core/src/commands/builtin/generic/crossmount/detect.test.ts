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

import { describe, expect, it } from 'vitest'
import { CROSS_MOUNT_COMMANDS, RELAY_COMMANDS, STREAM_COMMANDS } from './constants.ts'
import { strategyFor } from './detect.ts'
import { Cmd, Strategy } from './types.ts'

describe('strategyFor — mirrors tests/commands/builtin/generic/crossmount/test_detect.py', () => {
  it('keeps the two membership-tested sets disjoint and cross-mount capable', () => {
    // FANOUT is `detect`'s fallthrough rather than a set it consults, so
    // the only overlap that can change an answer is stream-vs-relay.
    expect([...STREAM_COMMANDS].some((name) => RELAY_COMMANDS.has(name))).toBe(false)
    for (const name of [...STREAM_COMMANDS, ...RELAY_COMMANDS]) {
      expect(CROSS_MOUNT_COMMANDS.has(name)).toBe(true)
    }
  })

  it('streams the whole-content commands', () => {
    for (const name of [Cmd.CAT, Cmd.NL, Cmd.CUT, Cmd.AWK]) {
      expect(strategyFor(name, {})).toBe(Strategy.STREAM)
    }
  })

  it('fans out the per-operand commands', () => {
    for (const name of [Cmd.GREP, Cmd.SHA256SUM, Cmd.RM, Cmd.TEE, Cmd.REV]) {
      expect(strategyFor(name, {})).toBe(Strategy.FANOUT)
    }
  })

  it('relays the commands whose operands must colocate', () => {
    for (const name of [Cmd.CP, Cmd.MV, Cmd.DIFF, Cmd.CMP, Cmd.SORT, Cmd.WC]) {
      expect(strategyFor(name, {})).toBe(Strategy.RELAY)
    }
  })

  it('relays ls because its layout spans the whole line', () => {
    // A per-operand run sees one operand, so it can neither head its
    // block nor sort against the operands living on other mounts.
    expect(strategyFor(Cmd.LS, {})).toBe(Strategy.RELAY)
  })

  it('streams sed by default but fans it out in place', () => {
    expect(strategyFor(Cmd.SED, {})).toBe(Strategy.STREAM)
    expect(strategyFor(Cmd.SED, { i: true })).toBe(Strategy.FANOUT)
  })
})
