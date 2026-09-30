import { describe, expect, it } from 'vitest'
import { departed } from './diff.ts'

function isFolder(kind: string): boolean {
  return kind === 'directory'
}

describe('departed', () => {
  it.each(['/mount', '/mount/'])('reports only topmost paths under %s', (prefix) => {
    const previous = new Map([
      ['removed/child', 'file'],
      ['removed', 'directory'],
      ['removed-sibling', 'file'],
      ['kept/deleted', 'file'],
      ['kept', 'directory'],
      ['kept/live', 'file'],
    ])
    expect(departed(previous, ['kept', 'kept/live', 'new'], prefix, isFolder)).toEqual([
      { path: '/mount/kept/deleted', folder: false },
      { path: '/mount/removed', folder: true },
      { path: '/mount/removed-sibling', folder: false },
    ])
  })

  it.each(['', '/'])('classifies custom rows under root %s', (prefix) => {
    expect(
      departed(Object.entries({ directory: 'directory', file: 'file' }), [], prefix, isFolder),
    ).toEqual([
      { path: '/directory', folder: true },
      { path: '/file', folder: false },
    ])
  })

  it('ignores unchanged and new paths', () => {
    expect(departed(Object.entries({ kept: 'file' }), ['kept', 'new'], '/mount', isFolder)).toEqual(
      [],
    )
    expect(departed([], ['new'], '/mount', isFolder)).toEqual([])
  })
})
