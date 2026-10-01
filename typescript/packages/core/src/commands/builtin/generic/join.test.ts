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
import { MountMode } from '../../../types.ts'
import { RAMVFS } from '../../../vfs/ram/ram.ts'
import { getTestParser } from '../../../workspace/fixtures/workspace_fixture.ts'
import { Workspace } from '../../../workspace/workspace/workspace.ts'
import { CheckOrder, parseJoinFlags, type JoinFlags } from './join.ts'

type Row = [string, string, string, string, string, number, string, string]

// Each row is GNU join 9.7 (debian:stable-slim) run on files a and b; every
// string is a byte view, one character per byte. Mirrors GNU in test_join.py.
const GNU: Row[] = [
  [
    'a1a2',
    '1 a\n2 b\n3 c\n',
    '1 x\n3 z\n4 w\n',
    'join -a1 -a2 a b',
    '',
    0,
    '1 a x\n2 b\n3 c z\n4 w\n',
    '',
  ],
  ['v1v2', '1 a\n2 b\n3 c\n', '1 x\n3 z\n4 w\n', 'join -v1 -v2 a b', '', 0, '2 b\n4 w\n', ''],
  [
    'o_e',
    '1 a\n2 b\n3 c\n',
    '1 x\n3 z\n4 w\n',
    'join -a1 -a2 -e NA -o 0,1.2,2.2 a b',
    '',
    0,
    '1 a x\n2 b NA\n3 c z\n4 NA w\n',
    '',
  ],
  [
    'o_repeat',
    '1 a\n2 b\n3 c\n',
    '1 x\n3 z\n4 w\n',
    'join -o 1.1 -o 2.2,1.2 a b',
    '',
    0,
    '1 x a\n3 z c\n',
    '',
  ],
  [
    'o_trailing_comma',
    '1 a\n2 b\n3 c\n',
    '1 x\n3 z\n4 w\n',
    'join -o 1.1, a b',
    '',
    0,
    '1\n3\n',
    '',
  ],
  [
    'auto_a1a2',
    '1 a b c\n2 d\n3 e f\n',
    '1 x\n2 y z w\n4 q r\n',
    'join -o auto -a1 -a2 a b',
    '',
    0,
    '1 a b c x\n2 d   y\n3 e f  \n4    q\n',
    '',
  ],
  [
    'auto_e',
    '1 a b c\n2 d\n3 e f\n',
    '1 x\n2 y z w\n4 q r\n',
    'join -o auto -a1 -a2 -e NA a b',
    '',
    0,
    '1 a b c x\n2 d NA NA y\n3 e f NA NA\n4 NA NA NA q\n',
    '',
  ],
  [
    't_colon_e',
    '1:a::c\n2::b\n3:c\n',
    '1:x:\n2:y\n:z\n',
    'join -t : -e X a b',
    '',
    0,
    '1:a:X:c:x:X\n2:X:b:y\n',
    '',
  ],
  [
    't_whole_line_a',
    'x y\nz w\n',
    'x y\nz\n',
    "join -t '' -a1 -a2 -o 0,1.1 a b",
    '',
    0,
    'x y x y\nz \nz w z w\n',
    '',
  ],
  [
    't_newline_o',
    'x y\n',
    'x y\n',
    "join -t $'\\n' -o 0,1.1,2.1 a b",
    '',
    0,
    'x y\nx y\nx y\n',
    '',
  ],
  ['cr', '1 a\r\n2 b\r\n', '1 x\n2 y\n', 'join a b', '', 0, '1 a\r x\n2 b\r y\n', ''],
  ['ws_trailing', '1 a  \n2 b\t\n', '1 x \n2 y\n', 'join a b', '', 0, '1 a x\n2 b y\n', ''],
  ['i_toupper_order', 'A 1\n_ 2\n', '_ y\n', 'join -i a b', '', 0, '_ 2 y\n', ''],
  [
    'i_nonascii',
    '\xc3\x89 1\n',
    '\xc3\xa9 x\n',
    'join -i -a1 -a2 a b',
    '',
    0,
    '\xc3\x89 1\n\xc3\xa9 x\n',
    '',
  ],
  ['j12', 'a 1\nb 2\n', '1 x\n2 y\n', 'join -1 2 -2 1 a b', '', 0, '1 a x\n2 b y\n', ''],
  [
    'j_huge',
    '1 a\n2 b\n3 c\n',
    '1 x\n3 z\n4 w\n',
    'join -1 99999999999999999999999 -a1 a b',
    '',
    0,
    ' 1 a\n 2 b\n 3 c\n',
    '',
  ],
  [
    'header_a',
    'id name\n1 a\n2 b\n',
    'id val\n2 y\n3 z\n',
    'join --header -a1 -a2 a b',
    '',
    0,
    'id name val\n1 a\n2 b y\n3 z\n',
    '',
  ],
  [
    'header_disorder_body',
    'k h\nb 1\na 2\n',
    'k g\na x\n',
    'join --header a b',
    '',
    1,
    'k h g\n',
    'join: a:3: is not sorted: a 2\njoin: input is not in sorted order\n',
  ],
  [
    'z_newline_fieldsep',
    '1\na\x002 b\x00',
    '1 x\n\x002\ny\x00',
    'join -z a b',
    '',
    0,
    '1 a x\x002 b y\x00',
    '',
  ],
  [
    'dup_cross_mixed',
    'a 1\nk 1\nk 2\nz 9\n',
    'k a\nk b\nm q\n',
    'join -a1 -a2 a b',
    '',
    0,
    'a 1\nk 1 a\nk 1 b\nk 2 a\nk 2 b\nm q\nz 9\n',
    '',
  ],
  [
    'unsorted_task',
    'b one\na two\n',
    'a x\nb y\n',
    'join a b',
    '',
    1,
    'b one y\n',
    'join: a:2: is not sorted: a two\njoin: input is not in sorted order\n',
  ],
  [
    'unsorted_task_nocheck',
    'b one\na two\n',
    'a x\nb y\n',
    'join --nocheck-order a b',
    '',
    0,
    'b one y\n',
    '',
  ],
  [
    'unsorted_task_check',
    'b one\na two\n',
    'a x\nb y\n',
    'join --check-order a b',
    '',
    1,
    '',
    'join: a:2: is not sorted: a two\n',
  ],
  [
    'check_then_nocheck',
    'b one\na two\n',
    'a x\nb y\n',
    'join --check-order --nocheck-order a b',
    '',
    0,
    'b one y\n',
    '',
  ],
  [
    'unsorted_check_fatal_mid',
    'a 1\nb 2\nd 4\nc 3\n',
    'a x\nb y\nc z\nd w\n',
    'join --check-order a b',
    '',
    1,
    'a 1 x\nb 2 y\n',
    'join: a:4: is not sorted: c 3\n',
  ],
  [
    'unsorted_both_a',
    'a 1\nd 4\nc 3\nb 9\n',
    'b x\ne y\nd z\nc w\n',
    'join -a1 -a2 a b',
    '',
    1,
    'a 1\nb x\nd 4\nc 3\nb 9\ne y\nd z\nc w\n',
    'join: a:3: is not sorted: c 3\njoin: b:3: is not sorted: d z\njoin: input is not in sorted order\n',
  ],
  [
    'unsorted_before_unpair',
    'b 1\na 2\nc 3\n',
    'b x\nc y\nd z\n',
    'join a b',
    '',
    0,
    'b 1 x\nc 3 y\n',
    '',
  ],
  ['seen_after_advance', 'a 1\nc 2\nb\x00x 3\n', 'a x\nz q\n', 'join a b', '', 0, 'a 1 x\n', ''],
  ['unsorted_tail1', 'a 1\nc 3\nb 2\n', 'a x\n', 'join a b', '', 0, 'a 1 x\n', ''],
  [
    'check_tail_fatal_a1',
    'a 1\nc 2\nb 3\n',
    'a x\n',
    'join --check-order -a1 a b',
    '',
    1,
    'a 1 x\nc 2\n',
    'join: a:3: is not sorted: b 3\n',
  ],
  [
    'unsorted_stdin_name',
    '',
    'a x\nc z\n',
    'join - b',
    'b 1\na 2\n',
    1,
    '',
    'join: -:2: is not sorted: a 2\njoin: input is not in sorted order\n',
  ],
  [
    'astral_vs_bmp_check',
    '\xef\xbc\x81 1\n\xf0\x9f\x98\x80 2\n',
    '\xef\xbc\x81 x\n\xf0\x9f\x98\x80 y\n',
    'join --check-order a b',
    '',
    0,
    '\xef\xbc\x81 1 x\n\xf0\x9f\x98\x80 2 y\n',
    '',
  ],
  [
    'bytes_invalid_order',
    'z 1\n\xff 2\n',
    '\xff x\na q\n',
    'join -a1 -a2 a b',
    '',
    1,
    'z 1\n\xff 2 x\na q\n',
    'join: b:2: is not sorted: a q\njoin: input is not in sorted order\n',
  ],
  [
    'nul_in_line_msg',
    'a 1\nc 2\nd 3\nb\x00x 4\n',
    'a x\nz q\n',
    'join a b',
    '',
    1,
    'a 1 x\n',
    'join: a:4: is not sorted: b\njoin: input is not in sorted order\n',
  ],
  [
    'a_bad',
    '1 a\n2 b\n3 c\n',
    '1 x\n3 z\n4 w\n',
    'join -a 3 a b',
    '',
    1,
    '',
    "join: invalid file number: '3'\n",
  ],
  [
    'f_suffix',
    '1 a\n2 b\n3 c\n',
    '1 x\n3 z\n4 w\n',
    'join -1 2x a b',
    '',
    1,
    '',
    "join: invalid field number: '2x'\n",
  ],
  [
    'j_conflict',
    '1 a\n2 b\n3 c\n',
    '1 x\n3 z\n4 w\n',
    'join -1 2 -j 3 a b',
    '',
    1,
    '',
    'join: incompatible join fields 1, 2\n',
  ],
  [
    'o_empty_item',
    '1 a\n2 b\n3 c\n',
    '1 x\n3 z\n4 w\n',
    'join -o 1.1,,2.1 a b',
    '',
    1,
    '',
    "join: invalid file number in field spec: ''\n",
  ],
  [
    'o_zero_dot',
    '1 a\n2 b\n3 c\n',
    '1 x\n3 z\n4 w\n',
    'join -o 0.1 a b',
    '',
    1,
    '',
    "join: invalid field specifier: '0.1'\n",
  ],
  [
    't_multibyte',
    '1\xc3\xa9a\n',
    '1\xc3\xa9x\n',
    'join -t é a b',
    '',
    1,
    '',
    "join: multi-character tab '\\303\\251'\n",
  ],
  [
    't_incompatible',
    '1 a\n2 b\n3 c\n',
    '1 x\n3 z\n4 w\n',
    'join -t : -t , a b',
    '',
    1,
    '',
    'join: incompatible tabs\n',
  ],
  [
    'e_conflict',
    '1 a\n2 b\n3 c\n',
    '1 x\n3 z\n4 w\n',
    'join -e A -e B a b',
    '',
    1,
    '',
    'join: conflicting empty-field replacement strings\n',
  ],
  [
    'missing_operand',
    '1 a\n2 b\n3 c\n',
    '1 x\n3 z\n4 w\n',
    'join a',
    '',
    1,
    '',
    "join: missing operand after 'a'\nTry 'join --help' for more information.\n",
  ],
]

function bytes(view: string): Uint8Array {
  return Uint8Array.from(view, (ch) => ch.charCodeAt(0))
}

function view(raw: Uint8Array): string {
  return String.fromCharCode(...raw)
}

async function shell(
  mounts: Record<string, Record<string, string>>,
  cmd: string,
  stdin: string,
): Promise<[number, string, string]> {
  const vfs: Record<string, RAMVFS> = {}
  for (const [prefix, files] of Object.entries(mounts)) {
    const ram = new RAMVFS()
    for (const [name, body] of Object.entries(files)) ram.store.files.set(name, bytes(body))
    vfs[prefix] = ram
  }
  const ws = new Workspace(vfs, { mode: MountMode.WRITE, shellParser: await getTestParser() })
  try {
    const io = await ws.shell(cmd, { stdin: stdin === '' ? null : bytes(stdin), cwd: '/data' })
    return [io.exitCode, view(io.stdout), view(io.stderr)]
  } finally {
    await ws.close()
  }
}

describe('join matches GNU', () => {
  it.each(GNU)('%s', async (_id, a, b, cmd, stdin, code, stdout, stderr) => {
    expect(await shell({ '/data/': { '/a': a, '/b': b } }, cmd, stdin)).toEqual([
      code,
      stdout,
      stderr,
    ])
  })
})

const DEFAULTS: JoinFlags = {
  field1: 0,
  field2: 0,
  tab: null,
  outputSeparator: ' ',
  unpairables1: false,
  unpairables2: false,
  pairables: true,
  emptyFiller: null,
  outlist: [],
  autoformat: false,
  ignoreCase: false,
  eol: '\n',
  checkOrder: CheckOrder.DEFAULT,
  header: false,
}

describe('parseJoinFlags', () => {
  it.each<[Record<string, string | boolean>, Partial<JoinFlags>]>([
    [{}, {}],
    [
      { a: '2', v: '1' },
      { unpairables1: true, unpairables2: true, pairables: false },
    ],
    [{ j: '3' }, { field1: 2, field2: 2 }],
    [{ t: '' }, { tab: '\n', outputSeparator: ' ' }],
    [{ t: '\\0' }, { tab: '\0', outputSeparator: '\0' }],
    [
      { o: '0,2.3 1.1' },
      {
        outlist: [
          [0, 0],
          [2, 2],
          [1, 0],
        ],
      },
    ],
    [
      { o: 'auto', zero_terminated: true },
      { autoformat: true, eol: '\0' },
    ],
    [{ nocheck_order: true }, { checkOrder: CheckOrder.DISABLED }],
  ])('%j', (flags, expected) => {
    expect(parseJoinFlags(flags)).toEqual({ ...DEFAULTS, ...expected })
  })
})

describe('join across mounts', () => {
  it('reads every flag through the relay', async () => {
    const r = await shell(
      { '/data/': { '/a': 'B 2\nx 1\n' }, '/data2/': { '/b': 'b y\nC z\n' } },
      'join -i -j 1 -a1 -a2 -e - -o 0,1.2,2.2 --nocheck-order /data/a /data2/b',
      '',
    )
    expect(r).toEqual([0, 'B 2 y\nC - z\nx 1 -\n', ''])
  })
})
