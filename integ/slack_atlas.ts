import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { start } from './server/kit/typescript/index.ts'
import type { JsonValue } from './server/kit/typescript/index.ts'
import { slackFake } from './server/slack/fake.ts'

type Json = Record<string, JsonValue>
type Request = (method: string, args?: Record<string, string>) => Promise<Json>

interface Call {
  task: string
  tool: string
  args: Json
  reply: string
  skip?: string
}

interface Corpus {
  workspace: Json
  calls: Call[]
}

const CORPUS = fileURLToPath(new URL('./truth/slack_atlas.json', import.meta.url))
const MESSAGE_COLUMNS = [
  'UserID',
  'UserName',
  'RealName',
  'Channel',
  'ThreadTs',
  'Text',
  'Time',
  'Cursor',
]
const CHANNEL_COLUMNS = ['ID', 'Name', 'Topic', 'Purpose', 'MemberCount', 'Cursor']
const CHANNEL_TYPES = ['public_channel', 'private_channel', 'im', 'mpim']
const ARGUMENTS: Record<string, string[]> = {
  channels_list: ['channel_types', 'sort', 'limit', 'cursor'],
  conversations_history: ['channel_id', 'limit', 'cursor', 'include_activity_messages'],
  conversations_search_messages: [
    'search_query',
    'filter_in_channel',
    'filter_users_from',
    'filter_date_before',
    'filter_date_after',
    'filter_date_on',
    'filter_date_during',
    'limit',
    'cursor',
  ],
}

function csv(columns: string[], rows: string[][]): string {
  const escape = (value: string): string =>
    /[",\r\n]|^\s/.test(value) ? `"${value.replaceAll('"', '""')}"` : value
  return [columns, ...rows].map((row) => row.map(escape).join(',')).join('\n') + '\n'
}

// Port of pkg/text/text_processor.go at v1.1.23, the formatter used by both
// history and search. This is client formatting, never a fix to fake replies.
function processText(raw: string): string {
  let text = raw
  for (const pattern of [
    /<(https?:\/\/[^>|]+)\|([^>]+)>/g,
    /\[([^\]]+)\]\((https?:\/\/[^)]+)\)/g,
    /<a\s+href=["']([^"']+)["'][^>]*>([^<]+)<\/a>/g,
  ]) {
    for (const match of [...text.matchAll(pattern)]) {
      const markdown = match[0].startsWith('[')
      const url = match[markdown ? 2 : 1]!
      const label = match[markdown ? 1 : 2]!
      const last = text.slice(text.lastIndexOf(match[0]) + match[0].length).trim() === ''
      text = text.replace(match[0], `${url} - ${label}${last ? '' : ','}`)
    }
  }
  const urls = [...text.matchAll(/https?:\/\/[^\s<>"{}|\\^`[\]]+/g)].map((m) => m[0])
  for (const [i, url] of urls.entries())
    text = text.replace(url, `___URL_PLACEHOLDER_${String.fromCharCode(48 + i)}___`)
  text = text.replace(/[^0-9\p{L}\p{M}\s.,\-_: /?=&%]/gu, '')
  for (const [i, url] of urls.entries())
    text = text.replace(`___URL_PLACEHOLDER_${String.fromCharCode(48 + i)}___`, url)
  return text.replace(/\s+/g, ' ').trim()
}

function userOf(users: Json[], value: JsonValue | undefined): Json {
  const id = String(value)
  return (
    users.find((u) => u.id === id || u.name === id.replace(/^@/, '')) ?? {
      id,
      name: id,
      real_name: id,
    }
  )
}

async function listChannels(request: Request, types: string[]): Promise<Json[]> {
  const channels: Json[] = []
  let cursor = ''
  do {
    const response = await request('conversations.list', {
      types: types.join(','),
      limit: '1000',
      cursor,
    })
    channels.push(...(response.channels as Json[]))
    cursor = String((response.response_metadata as Json).next_cursor)
  } while (cursor !== '')
  return channels
}

// Wire arguments and CSV fields follow pkg/handler/{channels,conversations}.go
// at https://github.com/korotovsky/slack-mcp-server/tree/v1.1.23.
// Resolve names from the fake's users/list and conversations/list responses,
// not the corpus: every value under comparison must travel through the fake.
async function replay(
  call: Call,
  request: Request,
  users: Json[],
  channels: Json[],
): Promise<string> {
  const allowed = ARGUMENTS[call.tool]
  if (allowed === undefined) throw new Error(`Unsupported tool ${call.tool}`)
  for (const key of Object.keys(call.args)) {
    if (!allowed.includes(key)) throw new Error(`Unsupported ${call.tool} argument ${key}`)
  }
  const args = call.args
  if (call.tool === 'channels_list') {
    let types = String(args.channel_types ?? 'public_channel')
      .split(',')
      .map((t) => t.trim())
      .filter((t) => CHANNEL_TYPES.includes(t))
    if (types.length === 0) types = ['public_channel', 'private_channel']
    const sorted = (await listChannels(request, types)).sort((a, b) =>
      String(a.id).localeCompare(String(b.id)),
    )
    const cursor = Buffer.from(String(args.cursor ?? ''), 'base64').toString('utf8')
    const start =
      cursor === ''
        ? 0
        : Math.max(
            0,
            sorted.findIndex((c) => String(c.id) > cursor),
          )
    const limit = Math.min(Number(args.limit) || 100, 999)
    const page = sorted.slice(start, start + limit)
    const next =
      start + limit < sorted.length ? Buffer.from(String(page.at(-1)!.id)).toString('base64') : ''
    if ((args.sort ?? 'popularity') === 'popularity')
      page.sort((a, b) => Number(b.num_members) - Number(a.num_members))
    return csv(
      CHANNEL_COLUMNS,
      page.map((c, i) => [
        String(c.id),
        `#${String(c.name)}`,
        String((c.topic as Json).value),
        String((c.purpose as Json).value),
        String(c.num_members),
        i === page.length - 1 ? next : '',
      ]),
    )
  }
  const search = call.tool === 'conversations_search_messages'
  let messages: Json[]
  let next = ''
  let channel = String(args.channel_id ?? '')
  if (!search) {
    channel = String(channels.find((c) => `#${String(c.name)}` === channel)?.id ?? channel)
    const result = await request('conversations.history', {
      channel,
      limit: String(args.limit || '50'),
      cursor: String(args.cursor ?? ''),
    })
    messages = (result.messages as Json[]).filter(
      (m) => !m.subtype || args.include_activity_messages,
    )
    next = String((result.response_metadata as Json).next_cursor ?? '')
  } else {
    const query = [String(args.search_query ?? '')]
    if (args.filter_in_channel) {
      const value = String(args.filter_in_channel)
      const c = channels.find((c) => c.id === value || `#${String(c.name)}` === value)
      if (c === undefined) throw new Error(`Unknown channel ${value}`)
      query.push(`in:##${String(c.name)}`)
    }
    if (args.filter_users_from)
      query.push(`from:<@${String(userOf(users, args.filter_users_from).id)}>`)
    for (const key of ['before', 'after', 'on', 'during']) {
      if (args[`filter_date_${key}`]) query.push(`${key}:${String(args[`filter_date_${key}`])}`)
    }
    const page = args.cursor
      ? Buffer.from(String(args.cursor), 'base64').toString('utf8').split(':')[1]!
      : '1'
    const result = await request('search.all', {
      query: query.filter(Boolean).join(' '),
      count: String(args.limit ?? 100),
      page,
      sort: 'score',
      sort_dir: 'desc',
      highlight: 'false',
    })
    const resultMessages = result.messages as Json
    messages = resultMessages.matches as Json[]
    const pagination = resultMessages.pagination as Json
    if (
      Number(pagination.per_page) * Number(pagination.page_count) <
      Number(pagination.total_count)
    )
      next = Buffer.from(`page:${String(Number(pagination.page_count) + 1)}`).toString('base64')
  }
  return csv(
    MESSAGE_COLUMNS,
    messages.map((m, i) => {
      const user = userOf(users, m.user)
      const thread = search
        ? (new URL(String(m.permalink)).searchParams.get('thread_ts') ?? '')
        : String(m.thread_ts ?? '')
      return [
        String(m.user),
        String(user.name),
        String(user.real_name),
        search ? `#${String((m.channel as Json).name)}` : channel,
        thread,
        processText(String(m.text)),
        String(m.ts),
        i === messages.length - 1 ? next : '',
      ]
    }),
  )
}

// Slack's private relevance scores cannot be reconstructed from its export.
// Keep every CSV field and duplicate row; only search result order is ignored.
// ProcessText collapses embedded newlines, so each message is exactly one line.
function comparable(reply: string, search: boolean): string {
  return search ? reply.trimEnd().split('\n').sort().join('\n') : reply
}

async function main(): Promise<void> {
  const corpus = JSON.parse(readFileSync(CORPUS, 'utf8')) as Corpus
  const root = mkdtempSync(join(tmpdir(), 'slack-atlas-'))
  mkdirSync(join(root, 'slack'))
  writeFileSync(join(root, 'slack', 'atlas.json'), JSON.stringify(corpus.workspace))
  const fake = await start(slackFake, 0, 'atlas', root)
  let failed = 0
  let skipped = 0
  try {
    const request: Request = async (method, args = {}) => {
      const response = await fetch(`${fake.endpoint}/api/${method}`, {
        method: 'POST',
        headers: {
          Authorization: 'Bearer xoxp-default',
          'Content-Type': 'application/x-www-form-urlencoded',
        },
        body: new URLSearchParams(args),
      })
      const reply = (await response.json()) as Json
      if (!response.ok || reply.ok !== true) throw new Error(`${method}: ${JSON.stringify(reply)}`)
      return reply
    }
    const users = (await request('users.list')).members as Json[]
    const channels = await listChannels(request, CHANNEL_TYPES)
    for (const [i, call] of corpus.calls.entries()) {
      const label = `${String(i).padStart(2, '0')} ${call.task} ${call.tool}`
      if (call.skip !== undefined) {
        skipped += 1
        process.stdout.write(`  skip ${label}  [${call.skip}]\n`)
        continue
      }
      const reply = await replay(call, request, users, channels)
      const search = call.tool === 'conversations_search_messages'
      if (comparable(reply, search) === comparable(call.reply, search)) {
        process.stdout.write(`  ok   ${label}\n`)
      } else {
        failed += 1
        process.stdout.write(
          `  FAIL ${label}\n  got: ${JSON.stringify(reply)}\n  want: ${JSON.stringify(call.reply)}\n`,
        )
      }
    }
  } finally {
    await fake.close()
    rmSync(root, { recursive: true, force: true })
  }
  const total = corpus.calls.length - skipped
  process.stdout.write(
    `slack atlas: ${String(total - failed)}/${String(total)} live replies reproduced, ${String(skipped)} skipped\n`,
  )
  if (failed > 0) process.exitCode = 1
}

await main()
