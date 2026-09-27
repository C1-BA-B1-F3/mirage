import { Buffer } from 'node:buffer'
import { expect, it, vi } from 'vitest'
import { AsyncLineIterator } from '../../io/async_line_iterator.ts'
import { IOResult, materialize } from '../../io/types.ts'
import { specOf } from '../spec/builtins.ts'
import { FlagView } from '../spec/flag_view.ts'
import type { FlagValue } from '../spec/types.ts'
import { parseFlags as grepFlags } from './generic/grep.ts'
import { parseFlags as rgFlags } from './generic/rg.ts'
import { grepInput } from './grep_binary.ts'
import { requiredNeedles } from './grep_prefilter.ts'
import { grepStream, type GrepStreamOptions } from './grep_scan.ts'
import { searchHaystack } from './rg_search.ts'

const ENC = new TextEncoder()
const PATTERNS = [
  String.raw`zzqqxx`,
  String.raw`zzqqxx|qqzzyy`,
  String.raw`zz.qxx`,
  String.raw`\bzzqqxx\b`,
  String.raw`^zzqqxx$`,
  String.raw`zz[abc]qxx`,
  String.raw`(zzqqxx|qqzzyy)+`,
  String.raw`(zz)?qqxx`,
  String.raw`zzq{2,3}xx`,
  String.raw`zz\.qxx`,
]

async function run(
  engine: string,
  data: Uint8Array,
  pat: RegExp,
  flags: Record<string, FlagValue>,
  size = 65536,
): Promise<[Uint8Array, number | boolean, Uint8Array | null]> {
  async function* source(): AsyncIterable<Uint8Array> {
    await Promise.resolve()
    for (let at = 0; at < data.length; at += size) yield data.subarray(at, at + size)
  }
  const io = new IOResult()
  if (engine === 'grep') {
    const f = grepFlags(new FlagView(flags, specOf('grep')))
    const out = await materialize(grepInput(source(), pat, f, 'f', true, io))
    return [out, io.exitCode, io.stderr === null ? null : await materialize(io.stderr)]
  }
  if (engine === 'rg') {
    const f = rgFlags(new FlagView(flags, specOf('rg')))
    const tally = { selected: false }
    const out = await materialize(searchHaystack(source(), pat, f, 'f', 'f', tally))
    return [out, tally.selected, null]
  }
  const out = await materialize(
    grepStream(source(), pat, {
      invert: false,
      lineNumbers: false,
      onlyMatching: false,
      maxCount: null,
      countOnly: true,
      beforeContext: 0,
      afterContext: 0,
      io,
    }),
  )
  return [out, io.exitCode, null]
}

it.each(['grep', 'rg', 'stream'])(
  '%s bounds line work by blocks across search forms',
  async (engine) => {
    for (const record of ['abcdefg\n', 'abcdefg\0', '\xffabcdef\n']) {
      const data = Buffer.from(record.repeat(40000), 'latin1')
      for (const pattern of PATTERNS)
        for (const fold of ['', 'i'])
          for (const flags of [{}, { c: true }, { args_l: true }, { q: true }]) {
            const method = 'readline'
            const spy = vi.spyOn(AsyncLineIterator.prototype, method)
            try {
              const [out, selected, error] = await run(
                engine,
                data,
                new RegExp(pattern, fold),
                flags,
              )
              expect(error).toBeNull()
              expect(selected).toBe(engine === 'rg' ? false : 1)
              expect(out).toEqual(
                ENC.encode(
                  engine === 'rg' ? '' : engine === 'stream' ? '0\n' : flags.c ? 'f:0\n' : '',
                ),
              )
              expect(
                spy.mock.calls.length,
                `${pattern}/${fold} ${JSON.stringify(flags)}`,
              ).toBeLessThan(50)
            } finally {
              spy.mockRestore()
            }
          }
    }
  },
)

it.each(['grep', 'rg'])(
  '%s preserves output, status and boundaries',
  async (engine) => {
    const data = Buffer.concat([
      ENC.encode(
        'other\n'.repeat(1000) +
          'é ZZQQXX 😀\nſ K İ ı\n' +
          'other\n'.repeat(1000) +
          'qqzzyy\nzz.qxx\nzz\0qxx\n',
      ),
      Buffer.from([122, 122, 255, 113, 120, 120, 10]),
      ENC.encode('qqxx'),
    ])
    const options: Record<string, FlagValue>[] = [
      { n: true, byte_offset: true },
      { c: true },
      { args_l: true },
      { files_without_match: true },
      { q: true },
      { m: 1 },
      { o: true, n: true, byte_offset: true },
      { v: true, c: true },
      { B: 2, A: 1 },
      { stop_on_nonmatch: true },
      { passthru: true },
    ]
    for (const size of [7, 4096, 65536])
      for (const flags of options)
        for (const pattern of [
          ...PATTERNS,
          's|k|i',
          'zzqqxx|',
          'zzq*',
          '[^z]',
          '(?=qq)qq',
          String.raw`(qq)\1`,
        ]) {
          const pat = new RegExp(pattern, 'i')
          const actual = await run(engine, data, pat, flags, size)
          const spy = vi
            .spyOn(AsyncLineIterator.prototype, 'skipNonmatchingLines')
            .mockReturnValue([0, 0])
          try {
            expect(actual, `${pattern} ${String(size)} ${JSON.stringify(flags)}`).toEqual(
              await run(engine, data, pat, flags, size),
            )
          } finally {
            spy.mockRestore()
          }
        }
  },
  30000,
)

it.each([
  'a*',
  'a?',
  'a{0,3}',
  'foo|',
  '[abc]',
  String.raw`(foo)\1`,
  String.raw`\x66oo`,
  '(?=foo)',
  '('.repeat(40) + 'foo' + ')'.repeat(40),
])('falls back for %s', (pattern) => {
  expect(requiredNeedles(new RegExp(pattern))).toBeNull()
})

it.each([
  ['s', 'ſ'],
  ['k', 'K'],
])('keeps Unicode folds of %s', (pattern, match) => {
  const prefilter = requiredNeedles(new RegExp(pattern, 'iu'))
  expect(prefilter).not.toBeNull()
  const view = new TextDecoder('latin1').decode(ENC.encode(match)).toLowerCase()
  expect(prefilter?.some((needle) => view.includes(needle))).toBe(true)
})

it('retains matches across regex combinations', () => {
  const atoms = [
    'a',
    'b',
    '[ab]',
    '.',
    String.raw`\w`,
    '(?:a|b)',
    '(?:a|)',
    '(?=a)',
    '(?!b)',
    '(?<!b)',
  ]
  const texts = ['']
  for (let size = 1; size < 6; size++) {
    for (let bits = 0; bits < 2 ** size; bits++) {
      texts.push(bits.toString(2).padStart(size, '0').replaceAll('0', 'a').replaceAll('1', 'b'))
    }
  }
  for (const left of atoms)
    for (const right of atoms) {
      for (const repeat of ['', '?', '*', '+', '{0,2}', '{1,2}']) {
        if (left.startsWith('(?') && !left.startsWith('(?:') && repeat !== '') continue
        for (const pattern of [`${left}${repeat}${right}`, `(?:${left}${repeat}|${right})`]) {
          const pat = new RegExp(pattern, 'i')
          const prefilter = requiredNeedles(pat)
          for (const text of texts) {
            if (prefilter === null || !pat.test(text)) continue
            expect(
              prefilter.some((needle) => text.toLowerCase().includes(needle)),
              pattern,
            ).toBe(true)
          }
        }
      }
    }
})

it.each([7, 16384, 65536])('preserves printed stream output at chunk size %i', async (size) => {
  const padding = 'é other\n'.repeat(5000)
  const data = ENC.encode(padding + 'é ZZQQXX 😀\n' + padding + 'tail zzqqxx')
  const pat = /zz.qxx/i
  const options: Partial<GrepStreamOptions>[] = [
    {},
    { lineNumbers: true },
    { byteOffsets: true },
    { lineNumbers: true, byteOffsets: true },
    { lineNumbers: true, byteOffsets: true, onlyMatching: true },
    { lineNumbers: true, byteOffsets: true, maxCount: 1 },
  ]
  async function* source(): AsyncIterable<Uint8Array> {
    await Promise.resolve()
    for (let at = 0; at < data.length; at += size) yield data.subarray(at, at + size)
  }
  async function scan(option: Partial<GrepStreamOptions>): Promise<[Uint8Array, number]> {
    const io = new IOResult({ exitCode: 1 })
    const out = await materialize(
      grepStream(source(), pat, {
        invert: false,
        lineNumbers: false,
        byteOffsets: false,
        onlyMatching: false,
        maxCount: null,
        countOnly: false,
        beforeContext: 0,
        afterContext: 0,
        ...option,
        io,
      }),
    )
    return [out, io.exitCode]
  }
  for (const option of options) {
    const actual = await scan(option)
    const unfiltered = vi
      .spyOn(AsyncLineIterator.prototype, 'skipNonmatchingLines')
      .mockReturnValue([0, 0])
    try {
      expect(actual).toEqual(await scan(option))
    } finally {
      unfiltered.mockRestore()
    }
    expect(actual[0].length).toBeGreaterThan(0)
    expect(actual[1]).toBe(0)
  }
})

it.each([
  [/zzqqxx/i, ['zzqqxx']],
  [/zzqqxx|qqzzyy/, ['zzqqxx', 'qqzzyy']],
  [/(?:zzqqxx)|(?:qqzzyy)/, ['zzqqxx', 'qqzzyy']],
  [/zz.qxx/, ['qxx']],
  [/\bfoo\b/, ['foo']],
  [/(?<!\w)(?:foo)(?!\w)/, ['foo']],
  [/foo[0-9]+/, ['foo']],
  [/a?bc/, ['bc']],
  [/a{0,3}bc/, ['bc']],
  [/foo(?:bar)?/, ['foo']],
  [/foo|/, null],
  [/(?:foo)?/, null],
  [/\d+/, null],
  [/(?=foo)/, null],
  [/(foo)\1/, null],
  [/\x66oo/, null],
  [/foo/g, null],
  [/foo/y, null],
  [/é/, null],
] as const)('extracts a conservative requirement for %s', (pat, expected) => {
  expect(requiredNeedles(pat)).toEqual(expected)
})

it('never rejects a matching line across combinations of regex operators', () => {
  const atoms = ['a', 'bc', '[ab]', '.', '\\b', '(?:a|bc)', '(a|)', 'a?b', 'a{0,2}']
  const texts = ['', 'a', 'b', 'c', 'ab', 'abc', 'bc', 'ac', 'bb', 'aabc', 'bcc', 'abcabc']
  for (const left of atoms)
    for (const right of atoms)
      for (const join of ['', '|']) {
        for (const suffix of ['', '?', '*', '+', '{0,2}', '{2}']) {
          const pat = new RegExp(`(?:${left}${join}${right})${suffix}`)
          const needles = requiredNeedles(pat)
          if (needles === null) continue
          for (const text of texts) {
            if (pat.test(text))
              expect(
                needles.some((n) => text.includes(n)),
                `${String(pat)}: ${text}`,
              ).toBe(true)
          }
        }
      }
})
