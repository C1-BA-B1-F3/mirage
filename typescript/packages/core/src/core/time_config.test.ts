import { describe, expect, it } from 'vitest'
import { normalizeSlackConfig } from '../vfs/slack/config.ts'
import { normalizeDiscordConfig } from '../vfs/discord/config.ts'
import { normalizeGCalConfig } from '../vfs/gcal/config.ts'

describe('mount time bounds', () => {
  for (const [name, normalize, credentials] of [
    ['slack', normalizeSlackConfig, { token: 'test' }],
    ['discord', normalizeDiscordConfig, { token: 'test' }],
    ['gcal', normalizeGCalConfig, { access_token: 'test' }],
  ] as const) {
    it(`${name} validates both bounds through snake_case config`, () => {
      expect(
        normalize({
          ...credentials,
          start_time: '2026-06-01T10:00:00+08:00',
          end_time: '2026-06-01T03:00:00Z',
        }).startTime,
      ).toBe('2026-06-01T10:00:00+08:00')
      expect(normalize({ ...credentials, start_time: null, end_time: null }).endTime).toBeNull()
      for (const [start, end] of [
        ['2026-06-01', null],
        ['2026-06-01T10:00:00', null],
        ['2026-02-30T10:00:00Z', null],
        ['2026-06-01T24:00:00Z', null],
        ['2026-02-30T10:00:00Z', null],
        ['2026-06-01T10:00:00+01:60', null],
        ['2026-02-30T10:00:00Z', null],
        ['0000-06-01T10:00:00Z', null],
        ['2026-06-01T10:00:00.000001Z', null],
        ['2026-06-01T10:00:00Z', '2026-06-01T10:00:00Z'],
        ['2026-06-01T10:00:00Z', '2026-06-01T10:00:00+08:00'],
      ])
        expect(() => normalize({ ...credentials, start_time: start, end_time: end })).toThrow()
    })
  }
})
