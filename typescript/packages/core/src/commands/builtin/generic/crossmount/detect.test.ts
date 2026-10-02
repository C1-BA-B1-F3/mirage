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
import { MountMode, PathSpec } from '../../../../types.ts'
import { RAMVFS } from '../../../../vfs/ram/ram.ts'
import { MountRegistry } from '../../../../workspace/mount/registry.ts'
import { CROSS_MOUNT_COMMANDS, RELAY_COMMANDS, STREAM_COMMANDS } from './constants.ts'
import { isCrossMount, strategyFor } from './detect.ts'
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
    for (const name of [Cmd.CAT, Cmd.NL, Cmd.CUT]) {
      expect(strategyFor(name)).toBe(Strategy.STREAM)
    }
  })

  it('fans out the per-operand commands', () => {
    for (const name of [Cmd.HEAD, Cmd.SHA256SUM, Cmd.RM, Cmd.TEE, Cmd.REV]) {
      expect(strategyFor(name)).toBe(Strategy.FANOUT)
    }
  })

  it('relays the commands whose operands must colocate', () => {
    for (const name of [
      Cmd.CP,
      Cmd.MV,
      Cmd.DIFF,
      Cmd.CMP,
      Cmd.SORT,
      Cmd.WC,
      Cmd.GREP,
      Cmd.RG,
      Cmd.REALPATH,
    ]) {
      expect(strategyFor(name)).toBe(Strategy.RELAY)
    }
  })

  it('relays awk because it tells its operands apart', () => {
    // FILENAME, FNR, ARGV and a var=value operand between two files all
    // need each file as its own input, which a merged stream loses.
    expect(strategyFor(Cmd.AWK)).toBe(Strategy.RELAY)
  })

  it('relays ls because its layout spans the whole line', () => {
    // A per-operand run sees one operand, so it can neither head its
    // block nor sort against the operands living on other mounts.
    expect(strategyFor(Cmd.LS)).toBe(Strategy.RELAY)
  })

  it('relays sed to keep file boundaries and shared output', () => {
    expect(strategyFor(Cmd.SED)).toBe(Strategy.RELAY)
  })
})

describe('isCrossMount — mirrors tests/commands/builtin/generic/crossmount/test_detect.py', () => {
  it('crosses cp for a source holding a mount, not the destination', () => {
    const registry = new MountRegistry(
      { '/a': new RAMVFS(), '/a/d/n': new RAMVFS() },
      MountMode.WRITE,
    )
    const tree = PathSpec.fromStrPath('/a/d')
    const file = PathSpec.fromStrPath('/a/f.txt')
    const into = PathSpec.fromStrPath('/a/e')
    expect(isCrossMount('cp', [tree, into], registry)).toBe(true)
    expect(isCrossMount('cp', [file, tree], registry)).toBe(false)
    expect(isCrossMount('cp', [into, tree], registry, [into])).toBe(true)
    expect(isCrossMount('cp', [tree, file], registry, [tree])).toBe(false)
  })
})
