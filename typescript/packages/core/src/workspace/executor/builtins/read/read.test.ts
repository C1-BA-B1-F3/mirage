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
import { RAMVFS } from '../../../../vfs/ram/ram.ts'
import { MountMode } from '../../../../types.ts'
import { getTestParser } from '../../../fixtures/workspace_fixture.ts'
import { Workspace } from '../../../workspace/workspace.ts'

// What bash printed for each line (debian:stable-slim): the commands a
// group, loop, list, function or nested shell runs read one descriptor,
// so `read` takes its own and the next command reads on from there.
// Mirrors python's test_read.py.
const READ_LEAVES_THE_REST: [string, string][] = [
  ['printf \'a\\nb\\n\' | { read x; echo "[$x]"; cat; }', '[a]\nb\n'],
  ["printf 'a\\nb\\n' | sh -c 'read x; echo \"[$x]\"; cat'", '[a]\nb\n'],
  ['printf \'a\\nb\\nc\\n\' | { ( read x; echo "[$x]" ); cat; }', '[a]\nb\nc\n'],
  ['printf \'a\\nb\\nc\\n\' | { read x; read y; echo "$x $y"; cat; }', 'a b\nc\n'],
  ['printf \'a\\nb\\n\' | { read -n1 x; echo "[$x]"; cat; }', '[a]\n\nb\n'],
  ['printf \'abc\\ndef\\n\' | { read -N2 x; echo "[$x]"; cat; }', '[ab]\nc\ndef\n'],
  ['printf \'a:b\\nc\\n\' | { read -d: x; echo "[$x]"; cat; }', '[a]\nb\nc\n'],
  ['printf \'a\\nb\\n\' | { cat; read x; echo "[$x]"; }', 'a\nb\n[]\n'],
  ['printf \'a\\nb\\nc\\n\' | while read x; do echo "[$x]"; cat; done', '[a]\nb\nc\n'],
  [
    'printf \'a\\nb\\nc\\n\' | { read x; for i in 1 2; do read y; echo "[$y]"; done; }',
    '[b]\n[c]\n',
  ],
  ['f() { read x; echo "[$x]"; }; printf \'a\\nb\\nc\\n\' | { f; f; cat; }', '[a]\n[b]\nc\n'],
  ["printf 'a\\nb\\nc\\n' | { eval 'read x'; echo \"[$x]\"; cat; }", '[a]\nb\nc\n'],
  [
    "printf 'read y; echo \"[$y]\"\\n' > /data/s.sh; printf 'a\\nb\\n' | { source /data/s.sh; cat; }",
    '[a]\nb\n',
  ],
  ["printf 'a\\nb\\nc\\n' | { read x && cat; }", 'b\nc\n'],
  ['printf \'a\\nb\\n\' | case x in x) read a; read b; echo "$a$b";; esac', 'ab\n'],
  ['printf \'a\\nb\\nc\\n\' | { read x; mapfile -t r; echo "[$x] ${#r[@]}"; }', '[a] 2\n'],
  ['printf \'1\\n2\\n\' | { select v in p q; do echo "[$v]"; break; done; cat; }', '[p]\n2\n'],
  ["printf 'a\\nb\\nc\\n' | { read x; xargs echo; }", 'b c\n'],
  ['printf \'a\\nb\\n\' > /data/f; { read x; echo "[$x]"; cat; } < /data/f', '[a]\nb\n'],
  ['{ read x; echo "[$x]"; cat; } <<< $\'a\\nb\'', '[a]\nb\n'],
  [
    'printf \'a\\nb\\nc\\n\' > /data/f; exec < /data/f; read x; read y; echo "[$x][$y]"',
    '[a][b]\n',
  ],
  ["read x <<< ''; read y <<< ''; echo \"$? [$y]\"", '0 []\n'],
]

describe('read leaves the rest for the next command', () => {
  it.each(READ_LEAVES_THE_REST)('%s', async (line, expected) => {
    const parser = await getTestParser()
    const ws = new Workspace({ '/': new RAMVFS() }, { mode: MountMode.WRITE, shellParser: parser })
    await ws.shell('mkdir -p /data')
    const io = await ws.shell(line)
    expect([io.stdoutText, io.exitCode]).toEqual([expected, 0])
    await ws.close()
  })
})
