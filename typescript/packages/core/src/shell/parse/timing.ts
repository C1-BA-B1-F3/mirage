import type { Parser } from 'web-tree-sitter'
import type { HeredocNode } from './heredoc/node.ts'
import type { ShellNode } from '../types.ts'
import type { HeredocSource } from './heredoc/types.ts'

const PREFIX =
  /^time(?=[ \t\r\n;|&)]|$)[ \t]*(?:(-p)(?=[ \t\r\n;|&)]|$)[ \t]*)?(?:--(?=[ \t\r\n;|&)]|$)[ \t]*)?/
const STATEMENTS = new Set([
  'command',
  'test_command',
  'arithmetic_expansion',
  'pipeline',
  'redirected_statement',
  'negated_command',
  'subshell',
  'compound_statement',
  'if_statement',
  'for_statement',
  'while_statement',
  'case_statement',
])
export type TimingMark = readonly [number, boolean, number, number]

function sourceOffset(source: HeredocSource, index: number): number {
  const offset = source.offsets[index]
  if (offset === undefined) throw new Error('timing prefix outside source map')
  return offset
}

/** Remove reserved prefixes so the grammar can read the complete pipeline/compound body. */
export function lowerTiming(parser: Parser, source: HeredocSource): [HeredocSource, TimingMark[]] {
  let text = source.source
  let marks: TimingMark[] = []
  for (;;) {
    const root = parser.parse(text)?.rootNode
    if (root === undefined) break
    const stack = [root]
    const edits: [number, number, string][] = []
    while (stack.length > 0) {
      const node = stack.pop()
      if (node === undefined) break
      stack.push(...node.children)
      if (node.type !== 'command') continue
      const name = node.childForFieldName('name')
      if (name?.text !== 'time' || node.children[0]?.id !== name.id) continue
      if (node.parent?.type === 'pipeline' && node.parent.namedChildren[0]?.id !== node.id) continue
      const match = PREFIX.exec(text.slice(name.startIndex))
      if (match === null) continue
      let end = name.startIndex + match[0].length
      while (end < text.length && [' ', '\t'].includes(text.charAt(end))) end += 1
      const empty = end === text.length || ['\n', ';', '&', ')'].includes(text.charAt(end))
      let replacement = ' '.repeat(end - name.startIndex)
      let anchor = end
      if (empty) {
        replacement = ':' + replacement.slice(1)
        anchor = name.startIndex
      }
      marks = marks.map(([position, flag, begin, finish]) => [
        position === source.offsets[name.startIndex] ? sourceOffset(source, anchor) : position,
        flag,
        begin,
        finish,
      ])
      marks.push([
        sourceOffset(source, anchor),
        match[1] !== undefined,
        sourceOffset(source, name.startIndex),
        sourceOffset(source, end),
      ])
      edits.push([name.startIndex, end, replacement])
    }
    if (edits.length === 0) break
    for (const [start, end, replacement] of edits.sort((a, b) => b[0] - a[0]))
      text = text.slice(0, start) + replacement + text.slice(end)
  }
  return [{ ...source, source: text }, marks]
}

export class TimingNode implements ShellNode {
  readonly timing: readonly boolean[]
  constructor(
    private readonly node: HeredocNode,
    private readonly targets: ReadonlyMap<number, readonly boolean[]>,
    private readonly source: HeredocSource,
    private readonly spans: readonly (readonly [number, number])[],
    skip = false,
  ) {
    this.timing = skip ? [] : (targets.get(node.id) ?? [])
  }
  get type(): string {
    return this.timing.length > 0 ? 'timed_statement' : this.node.type
  }
  get text(): string {
    return this.node.text
  }
  get id(): number {
    return this.node.id
  }
  get startIndex(): number {
    return this.node.startIndex
  }
  get endIndex(): number {
    return this.node.endIndex
  }
  get startPosition() {
    return this.node.startPosition
  }
  get endPosition() {
    return this.node.endPosition
  }
  get isNamed(): boolean {
    return this.node.isNamed
  }
  get isMissing(): boolean {
    return this.node.isMissing
  }
  get hasError(): boolean {
    return this.node.hasError
  }
  get childCount(): number {
    return this.children.length
  }
  child(index: number): TimingNode | null {
    return this.children[index] ?? null
  }
  get children(): TimingNode[] {
    return this.timing.length > 0
      ? [new TimingNode(this.node, this.targets, this.source, this.spans, true)]
      : this.node.children.map(
          (node) => new TimingNode(node, this.targets, this.source, this.spans),
        )
  }
  get namedChildren(): TimingNode[] {
    return this.timing.length > 0
      ? this.children
      : this.node.namedChildren.map(
          (node) => new TimingNode(node, this.targets, this.source, this.spans),
        )
  }
  private wrap(node: HeredocNode | null): TimingNode | null {
    return node === null ? null : new TimingNode(node, this.targets, this.source, this.spans)
  }
  get parent(): TimingNode | null {
    return this.wrap(this.node.parent)
  }
  get previousSibling(): TimingNode | null {
    return this.wrap(this.node.previousSibling)
  }
  get nextSibling(): TimingNode | null {
    return this.wrap(this.node.nextSibling)
  }
  childForFieldName(name: string): TimingNode | null {
    return this.wrap(this.node.childForFieldName(name))
  }
  get sourceText(): string {
    if (this.source.documents.some(([start]) => this.startIndex <= start && start < this.endIndex))
      return this.node.sourceText
    const text = this.node.text.split('')
    for (let index = this.startIndex; index < this.endIndex; index += 1) {
      const offset = sourceOffset(this.source, index)
      if (this.spans.some(([start, end]) => start <= offset && offset < end))
        text[index - this.startIndex] = this.source.original.charAt(offset)
    }
    return text.join('')
  }
  get heredoc() {
    return this.node.heredoc
  }
  get warnings(): string {
    return this.node.warnings
  }
}

/** Attach each prefix to the complete next pipeline, stopping at list boundaries. */
export function wrapTiming(
  root: HeredocNode,
  source: HeredocSource,
  marks: readonly TimingMark[],
): TimingNode {
  const targets = new Map<number, readonly boolean[]>()
  for (const [position, portable] of marks) {
    const stack = [root]
    while (stack.length > 0) {
      const node = stack.pop()
      if (node === undefined) break
      if (STATEMENTS.has(node.type) && source.offsets[node.startIndex] === position) {
        targets.set(node.id, [portable || (targets.get(node.id) ?? []).some(Boolean)])
        break
      }
      stack.push(...[...node.namedChildren].reverse())
    }
  }
  return new TimingNode(
    root,
    targets,
    source,
    marks.map(([, , start, end]) => [start, end]),
  )
}
