import type { SheetTab } from '../store/types.ts'
import { asObj } from '../wire/json.ts'
import type { JsonObj } from '../wire/json.ts'
import { formatNumber } from './number.ts'

const DECIMAL = /^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$/

export function inputValue(value: string | number | boolean, option = 'USER_ENTERED'): JsonObj {
  if (typeof value === 'number') return { numberValue: value }
  if (typeof value === 'boolean') return { boolValue: value }
  if (option === 'RAW') return { stringValue: value }
  if (value.startsWith("'")) return { stringValue: value.slice(1) }
  if (value.startsWith('=')) return { formulaValue: value }
  const trimmed = value.trim()
  if (/^(true|false)$/i.test(trimmed)) return { boolValue: trimmed.toLowerCase() === 'true' }
  if (DECIMAL.test(trimmed) && Number.isFinite(Number(trimmed)))
    return { numberValue: Number(trimmed) }
  return { stringValue: value }
}

export function enteredValue(tab: SheetTab, key: string): JsonObj {
  if (!tab.cells.has(key) || tab.cells.get(key) === '') return {}
  return tab.props.get(key)?.userEnteredValue === undefined
    ? inputValue(tab.cells.get(key) ?? '')
    : asObj(tab.props.get(key)?.userEnteredValue)
}

function scientific(value: number): string {
  const [mantissa = '', exponent = ''] = value.toExponential(2).split('e')
  const sign = exponent.startsWith('-') ? '-' : '+'
  const digits = exponent.replace(/^[+-]/, '').padStart(2, '0')
  return `${mantissa}E${sign}${digits}`
}

const ERRORS: Record<string, string> = {
  ERROR: '#ERROR!',
  DIVIDE_BY_ZERO: '#DIV/0!',
  VALUE: '#VALUE!',
  REF: '#REF!',
  NAME: '#NAME?',
  NUM: '#NUM!',
}

export function formattedValue(
  value: JsonObj,
  numberFormat?: JsonObj,
  scientificInput = false,
): string {
  if (typeof value.numberValue === 'number') {
    return (
      (numberFormat === undefined ? null : formatNumber(value.numberValue, numberFormat)) ??
      (scientificInput ? scientific(value.numberValue) : String(value.numberValue))
    )
  }
  if (typeof value.boolValue === 'boolean') return value.boolValue ? 'TRUE' : 'FALSE'
  if (typeof value.stringValue === 'string') return value.stringValue
  if (value.errorValue !== undefined)
    return ERRORS[String(asObj(value.errorValue).type)] ?? '#ERROR!'
  return ''
}
