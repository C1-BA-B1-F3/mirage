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

import type { CommitFacts } from './format.ts'
import { CommitGraph } from './graph.ts'

function commit(oid: string, parents: string[] = []): CommitFacts {
  return {
    oid,
    tree: '',
    message: oid,
    authorName: '',
    authorEmail: '',
    authorTime: 0,
    authorTimezoneMinutes: 0,
    committerName: '',
    committerEmail: '',
    committerTime: 0,
    committerTimezoneMinutes: 0,
    parents,
  }
}

/** The graph lines `--oneline` prints, one commit per call, in walk order. */
function drawn(commits: CommitFacts[], firstParent = false): string[] {
  const shown = new Set(commits.map((each) => each.oid))
  const graph = new CommitGraph((oid) => shown.has(oid), firstParent)
  const lines: string[] = []
  for (const each of commits) {
    graph.update(each)
    const text = graph.showCommit() + each.oid + graph.showMessage('')
    lines.push(...text.split('\n'))
  }
  return lines
}

describe('CommitGraph', () => {
  // The issue's history, pinned against git 2.50.1: a merge whose second
  // parent's line is drawn first, then collapses back into the first.
  it('draws a merge and collapses its branch line', () => {
    const history = [commit('M', ['C', 'B']), commit('B', ['A']), commit('C', ['A']), commit('A')]
    expect(drawn(history)).toEqual(['*   M', '|\\  ', '| * B', '* | C', '|/  ', '* A'])
  })

  it('widens the space around an octopus merge that has a column to its right', () => {
    const history = [
      commit('T', ['Z']),
      commit('O', ['A', 'B', 'C']),
      commit('C', ['Z']),
      commit('B', ['Z']),
      commit('A', ['Z']),
      commit('Z'),
    ]
    expect(drawn(history)).toEqual([
      '* T',
      '| *-.   O',
      '| |\\ \\  ',
      '| | | * C',
      '| |_|/  ',
      '|/| |   ',
      '| | * B',
      '| |/  ',
      '|/|   ',
      '| * A',
      '|/  ',
      '* Z',
    ])
  })

  it('draws a parent the walk does not show as no line at all', () => {
    const graph = new CommitGraph((oid) => oid !== 'X', false)
    graph.update(commit('M', ['A', 'X']))
    expect(graph.showCommit()).toBe('* ')
    expect(graph.isFinished()).toBe(true)
  })

  it('draws a merge as one line under --first-parent', () => {
    expect(drawn([commit('M', ['A', 'B']), commit('A')], true)).toEqual(['* M', '* A'])
  })

  it('marks a commit whose predecessor never finished with an ellipsis row', () => {
    const graph = new CommitGraph(() => true, false)
    graph.update(commit('M', ['A', 'B']))
    graph.update(commit('B', ['A']))
    expect(graph.showCommit()).toBe('... \n| * ')
  })
})
