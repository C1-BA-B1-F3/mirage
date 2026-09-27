import type { SheetTab } from '../store/types.ts'
import { asObj } from '../wire/json.ts'
import type { JsonObj } from '../wire/json.ts'
import { parseCell } from './a1.ts'
import { enteredValue } from './value.ts'

type Scalar = string | number | boolean | null
interface RangeValue {
  values: Scalar[]
}
type Value = Scalar | RangeValue

class FormulaError extends Error {
  constructor(
    readonly kind: string,
    message: string,
  ) {
    super(message)
  }
}

function scalar(value: Value): Scalar {
  if (typeof value === 'object' && value !== null) {
    if (value.values.length === 1) return value.values[0] ?? null
    throw new FormulaError('VALUE', 'Expected a single value.')
  }
  return value
}

function numeric(value: Value): number {
  const v = scalar(value)
  if (v === null || v === '') return 0
  if (typeof v === 'boolean') return Number(v)
  if (typeof v === 'number') return v
  const parsed = inputNumber(v)
  if (parsed === null) throw new FormulaError('VALUE', 'Expected a number.')
  return parsed
}

function inputNumber(value: string): number | null {
  return /^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$/.test(value.trim()) &&
    Number.isFinite(Number(value))
    ? Number(value)
    : null
}

function extended(value: Scalar): JsonObj {
  if (typeof value === 'string') return { stringValue: value }
  if (typeof value === 'boolean') return { boolValue: value }
  const number = value ?? 0
  if (!Number.isFinite(number)) throw new FormulaError('NUM', 'Result is not finite.')
  return { numberValue: number }
}

/** A read-scoped evaluator: memoization never survives a mutation. */
export class FormulaEvaluator {
  private readonly active = new Set<string>()
  private readonly memo = new Map<string, JsonObj>()
  private steps = 0
  private readonly bounds = new Map<SheetTab, { rows: number; cols: number }>()
  constructor(private readonly tabs: readonly SheetTab[]) {}

  private gridSize(tab: SheetTab): { rows: number; cols: number } {
    const cached = this.bounds.get(tab)
    if (cached !== undefined) return cached
    const size = { rows: tab.rows, cols: tab.cols }
    for (const key of tab.cells.keys()) {
      const [row = 0, col = 0] = key.split(',').map(Number)
      size.rows = Math.max(size.rows, row + 1)
      size.cols = Math.max(size.cols, col + 1)
    }
    this.bounds.set(tab, size)
    return size
  }

  tick(): void {
    this.steps += 1
    if (this.steps > 100_000) throw new FormulaError('ERROR', 'Formula evaluation limit exceeded.')
  }

  cell(tab: SheetTab, row: number, col: number): JsonObj {
    const key = `${String(row)},${String(col)}`
    const id = `${String(tab.sheetId)}:${key}`
    const entered = enteredValue(tab, key)
    if (typeof entered.formulaValue !== 'string') return entered
    const cached = this.memo.get(id)
    if (cached !== undefined) return cached
    let value: JsonObj
    try {
      this.tick()
      if (this.active.has(id)) throw new FormulaError('REF', 'Circular dependency detected.')
      if (this.active.size >= 128)
        throw new FormulaError('ERROR', 'Formula dependency limit exceeded.')
      this.active.add(id)
      try {
        value = extended(scalar(new Parser(entered.formulaValue.slice(1), this, tab).parse()))
      } finally {
        this.active.delete(id)
      }
    } catch (error) {
      if (!(error instanceof FormulaError)) throw error
      value = { errorValue: { type: error.kind, message: error.message } }
    }
    this.memo.set(id, value)
    return value
  }

  reference(current: SheetTab, name: string | undefined, first: string, last?: string): Value {
    const tab =
      name === undefined
        ? current
        : this.tabs.find((t) => t.title.toLowerCase() === name.toLowerCase())
    if (tab === undefined) throw new FormulaError('REF', `Unknown sheet: ${name ?? ''}.`)
    const bounds = this.gridSize(tab)
    const start = parseCell(first.replaceAll('$', ''))
    const end = last === undefined ? start : parseCell(last.replaceAll('$', ''))
    if (
      start.row === null ||
      start.col === null ||
      end.row === null ||
      end.col === null ||
      start.row < 0 ||
      start.col < 0 ||
      end.row < start.row ||
      end.col < start.col ||
      end.row >= bounds.rows ||
      end.col >= bounds.cols
    )
      throw new FormulaError('REF', 'Invalid cell reference.')
    const values: Scalar[] = []
    for (let r = start.row; r <= end.row; r += 1) {
      for (let c = start.col; c <= end.col; c += 1) {
        this.tick()
        const v = this.cell(tab, r, c)
        if (v.errorValue !== undefined) {
          const error = asObj(v.errorValue)
          throw new FormulaError(String(error.type), String(error.message))
        }
        values.push(
          typeof v.numberValue === 'number'
            ? v.numberValue
            : typeof v.boolValue === 'boolean'
              ? v.boolValue
              : typeof v.stringValue === 'string'
                ? v.stringValue
                : null,
        )
      }
    }
    return { values }
  }
}

/** Deliberately bounded grammar; unsupported syntax never executes host code. */
class Parser {
  private at = 0
  private depth = 0
  constructor(
    private readonly text: string,
    private readonly evaluator: FormulaEvaluator,
    private readonly tab: SheetTab,
  ) {}

  private take(pattern: RegExp): string | undefined {
    this.textSpace()
    const found = pattern.exec(this.text.slice(this.at))?.[0]
    if (found !== undefined) this.at += found.length
    return found
  }

  private textSpace(): void {
    while (/\s/.test(this.text[this.at] ?? '') && this.at < this.text.length) this.at += 1
  }

  parse(): Value {
    if (this.text.length > 10_000) throw new FormulaError('ERROR', 'Formula is too long.')
    const value = this.expression()
    this.textSpace()
    if (this.at !== this.text.length) throw new FormulaError('ERROR', 'Formula parse error.')
    return value
  }

  private expression(): Value {
    let value = this.product()
    let op: string | undefined
    while ((op = this.take(/^[+-]/)) !== undefined) {
      const right = numeric(this.product())
      value = op === '+' ? numeric(value) + right : numeric(value) - right
    }
    return value
  }

  private product(): Value {
    let value = this.primary()
    let op: string | undefined
    while ((op = this.take(/^[*/]/)) !== undefined) {
      const right = numeric(this.primary())
      if (op === '/' && right === 0) throw new FormulaError('DIVIDE_BY_ZERO', 'Division by zero.')
      value = op === '*' ? numeric(value) * right : numeric(value) / right
    }
    return value
  }

  private primary(): Value {
    this.evaluator.tick()
    this.depth += 1
    if (this.depth > 128) throw new FormulaError('ERROR', 'Formula nesting limit exceeded.')
    try {
      return this.atom()
    } finally {
      this.depth -= 1
    }
  }

  private atom(): Value {
    const sign = this.take(/^[+-]/)
    if (sign !== undefined) return (sign === '-' ? -1 : 1) * numeric(this.primary())
    if (this.take(/^\(/) !== undefined) {
      const value = this.expression()
      if (this.take(/^\)/) === undefined)
        throw new FormulaError('ERROR', 'Missing closing parenthesis.')
      return value
    }
    const quoted = this.take(/^"(?:[^"]|"")*"/)
    if (quoted !== undefined) return quoted.slice(1, -1).replaceAll('""', '"')
    const qualifier = this.take(/^(?:'(?:[^']|'')*'|[A-Za-z_][A-Za-z0-9_]*)!/)
    const ref = this.take(/^\$?[A-Za-z]+\$?\d+(?![A-Za-z0-9_(])/)
    if (ref !== undefined) {
      const name = qualifier?.slice(0, -1)
      const title = name?.startsWith("'") ? name.slice(1, -1).replaceAll("''", "'") : name
      let end: string | undefined
      if (this.take(/^:/) !== undefined) {
        end = this.take(/^\$?[A-Za-z]+\$?\d+/)
        if (end === undefined) throw new FormulaError('ERROR', 'Invalid range.')
      }
      return this.evaluator.reference(this.tab, title, ref, end)
    }
    if (qualifier !== undefined) throw new FormulaError('REF', 'Invalid sheet reference.')
    const number = this.take(/^(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?/)
    if (number !== undefined) return Number(number)
    const name = this.take(/^[A-Za-z_][A-Za-z0-9_.]*/)?.toUpperCase()
    if (name === undefined) throw new FormulaError('ERROR', 'Formula parse error.')
    if (this.take(/^\(/) === undefined) {
      if (name === 'TRUE' || name === 'FALSE') return name === 'TRUE'
      throw new FormulaError('NAME', `Unknown name: ${name}.`)
    }
    if (!['SUM', 'AVERAGE', 'MIN', 'MAX', 'COUNT'].includes(name))
      throw new FormulaError('NAME', `Unknown function: ${name}.`)
    const numbers: number[] = []
    if (this.take(/^\)/) === undefined) {
      do {
        const value = this.expression()
        if (typeof value === 'object' && value !== null) {
          for (const v of value.values) if (typeof v === 'number') numbers.push(v)
        } else if (value !== null) {
          if (name === 'COUNT') {
            if (
              typeof value === 'number' ||
              typeof value === 'boolean' ||
              (typeof value === 'string' && inputNumber(value) !== null)
            )
              numbers.push(numeric(value))
          } else numbers.push(numeric(value))
        }
      } while (this.take(/^,/) !== undefined)
      if (this.take(/^\)/) === undefined)
        throw new FormulaError('ERROR', 'Missing closing parenthesis.')
    }
    if (name === 'COUNT') return numbers.length
    if (name === 'AVERAGE' && numbers.length === 0)
      throw new FormulaError('DIVIDE_BY_ZERO', 'No numeric values to average.')
    if (name === 'MIN') return numbers.length === 0 ? 0 : numbers.reduce((a, b) => Math.min(a, b))
    if (name === 'MAX') return numbers.length === 0 ? 0 : numbers.reduce((a, b) => Math.max(a, b))
    const sum = numbers.reduce((a, b) => a + b, 0)
    return name === 'AVERAGE' ? sum / numbers.length : sum
  }
}
