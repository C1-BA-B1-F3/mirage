const TOKEN = /%\{([^}]*)\}|%%|\\([nrt\\])/g
const ESCAPES: Record<string, string> = { n: '\n', r: '\r', t: '\t', '\\': '\\' }

/** Format observable transfer facts; unavailable variables diagnose instead of inventing values. */
export function renderWriteOut(
  template: string,
  values: Readonly<Record<string, string>>,
): [Uint8Array, Uint8Array] {
  const streams: [string[], string[]] = [[], []]
  let stream: 0 | 1 = 0
  let cursor = 0
  for (const match of template.matchAll(TOKEN)) {
    streams[stream].push(template.slice(cursor, match.index))
    const name = match[1]
    if (name === 'stdout' || name === 'stderr') stream = name === 'stderr' ? 1 : 0
    else if (name === 'onerror') {
      if (values.exitcode === '0')
        return [
          new TextEncoder().encode(streams[0].join('')),
          new TextEncoder().encode(streams[1].join('')),
        ]
    } else if (name !== undefined) {
      if (Object.hasOwn(values, name)) streams[stream].push(values[name] ?? '')
      else streams[1].push(`curl: unknown --write-out variable: '${name}'\n`)
    } else if (match[2] !== undefined) streams[stream].push(ESCAPES[match[2]] ?? '')
    else streams[stream].push('%')
    cursor = match.index + match[0].length
  }
  streams[stream].push(template.slice(cursor))
  return [
    new TextEncoder().encode(streams[0].join('')),
    new TextEncoder().encode(streams[1].join('')),
  ]
}
