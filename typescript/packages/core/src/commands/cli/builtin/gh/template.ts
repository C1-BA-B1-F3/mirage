import { compareCodePoints } from '../../../../utils/sort.ts'
import type { JsonValue as Value } from '../../../../types.ts'
import { TEMPLATE_ACTION, TEMPLATE_DECLARATION, TEMPLATE_TOKEN } from './constants.ts'

type Variables = Map<string, { value: Value }>

function text(value: Value | undefined): string {
  if (value == null) return '<no value>'
  if (Array.isArray(value)) return `[${value.map(text).join(' ')}]`
  if (typeof value === 'object')
    return `map[${Object.keys(value)
      .sort(compareCodePoints)
      .map((key) => `${key}:${text(value[key])}`)
      .join(' ')}]`
  return String(value)
}
function lookup(token: string, dot: Value, root: Value, variables: Variables): Value {
  if (token.startsWith('"')) return JSON.parse(token) as Value
  if (token.startsWith('`')) return token.slice(1, -1)
  if (token === 'true' || token === 'false') return token === 'true'
  if (/^-?\d+$/.test(token)) return Number(token)
  if (token === '.') return dot
  let value = dot,
    path = token.replace(/^\.+/, '')
  if (token.startsWith('$')) {
    const at = token.indexOf('.'),
      name = at < 0 ? token : token.slice(0, at)
    path = at < 0 ? '' : token.slice(at + 1)
    const bound = variables.get(name)
    if (name !== '$' && bound === undefined)
      throw new Error(`template: undefined variable "${name}"`)
    value = bound === undefined ? root : bound.value
  }
  for (const key of path.split('.').filter(Boolean))
    value =
      typeof value === 'object' && value !== null && !Array.isArray(value)
        ? (value[key] ?? null)
        : null
  return value
}
function call(name: string, args: Value[]): Value {
  const a = args[0],
    b = args[1]
  switch (name) {
    case 'len':
      return typeof a === 'string' || Array.isArray(a)
        ? a.length
        : Object.keys(a as Record<string, Value>).length
    case 'join':
      return (b as Value[]).map(text).join(text(a))
    case 'pluck':
      return (b as Record<string, Value>[]).map((row) => row[text(a)] ?? null)
    case 'print':
      return args.map(text).join('')
    case 'println':
      return `${args.map(text).join(' ')}\n`
    case 'printf': {
      let i = 1
      return text(a).replace(/%(%|s|v|d|q|f)/g, (_, flag: string) =>
        flag === '%'
          ? '%'
          : flag === 'q'
            ? JSON.stringify(args[i++])
            : flag === 'f'
              ? Number(args[i++]).toFixed(6)
              : text(args[i++]),
      )
    }
    case 'index': {
      let v = a
      for (const key of args.slice(1))
        v = Array.isArray(v) ? v[Number(key)] : (v as Record<string, Value>)[text(key)]
      return v ?? null
    }
    case 'eq':
      return args.slice(1).some((value) => value === a)
    case 'ne':
      return a !== b
    case 'not':
      return !a
    case 'and':
      return args.every(Boolean)
    case 'or':
      return args.some(Boolean)
    case 'color':
    case 'autocolor':
    case 'hyperlink':
      return args.at(-1) ?? ''
    case 'truncate': {
      const n = Number(a),
        s = text(b)
      return s.length <= n ? s : s.slice(0, Math.max(0, n - 3)) + '.'.repeat(Math.min(n, 3))
    }
    case 'contains':
      return text(b).includes(text(a))
    case 'hasPrefix':
      return text(b).startsWith(text(a))
    case 'hasSuffix':
      return text(b).endsWith(text(a))
    default:
      throw new Error(`template: function "${name}" not defined`)
  }
}
function evaluate(expression: string, dot: Value, root: Value, variables: Variables): Value {
  const tokens = expression.match(TEMPLATE_TOKEN) ?? []
  const parts: string[][] = [[]]
  for (const token of tokens) {
    if (token === '|') parts.push([])
    else parts.at(-1)?.push(token)
  }
  let value: Value = null
  parts.forEach((part, i) => {
    const head = part[0]
    if (head === undefined) throw new Error('template: empty pipeline')
    const args = part.slice(1).map((token) => lookup(token, dot, root, variables))
    if (i > 0) args.push(value)
    value =
      part.length === 1 && i === 0 && (/^[.$"`]/.test(head) || /^(true|false|-?\d+)$/.test(head))
        ? lookup(head, dot, root, variables)
        : call(head, args)
  })
  return value
}

function declaration(expression: string): [string[], string, boolean] {
  const match = TEMPLATE_DECLARATION.exec(expression)
  if (match === null) return [[], expression, false]
  return [
    [match[1], match[2]].filter((name): name is string => name !== undefined),
    match[4] ?? '',
    match[3] === '=',
  ]
}

/** Render selected JSON with Go-style actions, pipelines and blocks. */
export function renderTemplate(template: string, value: Value): string {
  const tokens: [string, string][] = []
  let end = 0,
    trim = false
  for (const match of template.matchAll(TEMPLATE_ACTION)) {
    let segment = template.slice(end, match.index)
    if (trim) segment = segment.trimStart()
    if (match[1]) segment = segment.trimEnd()
    tokens.push(['text', segment], ['action', match[2] ?? ''])
    trim = Boolean(match[3])
    end = match.index + match[0].length
  }
  tokens.push(['text', trim ? template.slice(end).trimStart() : template.slice(end)])
  function render(start: number, stop: number, dot: Value, variables: Variables): string {
    const output: string[] = []
    for (let i = start; i < stop; ) {
      const [tag, action] = tokens[i++] ?? ['', '']
      if (tag === 'text') {
        output.push(action)
        continue
      }
      const command = action.split(' ')[0] ?? '',
        expression = action.slice(command.length + 1)
      if (['range', 'if', 'with'].includes(command)) {
        let depth = 1,
          cursor = i,
          alternate: number | undefined
        for (; cursor < stop; cursor++) {
          const [nestedTag, nestedAction] = tokens[cursor] ?? ['', '']
          if (nestedTag !== 'action') continue
          const nested = nestedAction.split(' ')[0] ?? ''
          if (['range', 'if', 'with'].includes(nested)) depth++
          else if (nested === 'end') {
            if (--depth === 0) break
          } else if (nested === 'else' && depth === 1) alternate = cursor
        }
        if (depth) throw new Error('template: unexpected EOF')
        const [names, pipeline] = declaration(expression)
        if (names.length > 1 && command !== 'range')
          throw new Error(`template: too many declarations in ${command}`)
        const resolved = evaluate(pipeline, dot, value, variables),
          bodyEnd = alternate ?? cursor
        const scope = new Map(variables)
        if (names[0] !== undefined && command !== 'range') scope.set(names[0], { value: resolved })
        const truthy = Boolean(resolved) && (!Array.isArray(resolved) || resolved.length > 0)
        if (command === 'range' && truthy) {
          const entries: [Value, Value][] = Array.isArray(resolved)
            ? resolved.map((item, index) => [index, item])
            : Object.keys(resolved as Record<string, Value>)
                .sort(compareCodePoints)
                .map((key) => [key, (resolved as Record<string, Value>)[key] ?? null])
          for (const [key, item] of entries) {
            const bound = new Map(variables)
            if (names.length === 2) bound.set(names[0] ?? '', { value: key })
            const last = names.at(-1)
            if (last !== undefined) bound.set(last, { value: item })
            output.push(render(i, bodyEnd, item, bound))
          }
        } else if (truthy)
          output.push(render(i, bodyEnd, command === 'with' ? resolved : dot, scope))
        else if (alternate !== undefined) output.push(render(alternate + 1, cursor, dot, scope))
        i = cursor + 1
      } else if (command === 'end' || command === 'else')
        throw new Error(`template: unexpected ${command}`)
      else {
        const [names, pipeline, assign] = declaration(action)
        const result = evaluate(pipeline, dot, value, variables),
          name = names[0]
        if (name === undefined) output.push(text(result))
        else if (!assign) variables.set(name, { value: result })
        else {
          const bound = variables.get(name)
          if (bound === undefined) throw new Error(`template: undefined variable "${name}"`)
          bound.value = result
        }
      }
    }
    return output.join('')
  }
  return render(0, tokens.length, value, new Map())
}
