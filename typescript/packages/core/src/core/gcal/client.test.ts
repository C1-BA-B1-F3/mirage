import { expect, it, vi } from 'vitest'
import * as googleClient from '../google/client.ts'
import { listEvents } from './client.ts'

const { googleGet } = vi.hoisted(() => ({ googleGet: vi.fn() }))
vi.mock('../google/client.ts', async (original) => ({
  ...(await original<typeof googleClient>()),
  googleGet,
}))

it('refuses a listing still paginated after 50 pages', async () => {
  googleGet.mockResolvedValue({ items: [], nextPageToken: 'more' })
  await expect(
    listEvents(
      new googleClient.TokenManager({ accessToken: 'test' }),
      'primary',
      null,
      '2026-08-12T00:00:00Z',
    ),
  ).rejects.toThrow('exceeded 50 pages')
  expect(googleGet).toHaveBeenCalledTimes(50)
  expect(googleGet.mock.calls[0]?.[2]).not.toHaveProperty('timeMin')
})
