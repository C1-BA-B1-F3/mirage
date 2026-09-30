import { spawn } from 'node:child_process'
import {
  createServer as createHttpServer,
  type IncomingMessage,
  type ServerResponse,
} from 'node:http'
import { mkdtemp, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { isDeepStrictEqual } from 'node:util'
import { Workspace } from '../../../typescript/packages/node/dist/workspace.js'
import { RAMVFS } from '../../../typescript/packages/core/dist/vfs/ram/ram.js'

const TENANT = 'gh-search-conformance'
const REPO = 'integ/repo-v1'
const MISSING_REPO_QUERY = '{ repository(owner: "integ", name: "missing") { name } }'
const HEADERS = {
  'x-mirage-run': TENANT,
  'x-mirage-tenant': 'default',
  authorization: 'token integ',
  'content-type': 'application/json',
}

function run(
  command: string,
  args: string[],
  env = process.env,
): Promise<{ code: number; stdout: string; stderr: string }> {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { env, stdio: ['ignore', 'pipe', 'pipe'] })
    let stdout = '',
      stderr = ''
    child.stdout.setEncoding('utf8').on('data', (data: string) => {
      stdout += data
    })
    child.stderr.setEncoding('utf8').on('data', (data: string) => {
      stderr += data
    })
    child.on('error', reject)
    child.on('close', (code) => resolve({ code: code ?? 1, stdout, stderr }))
  })
}

/**
 * Compare vanilla gh and Mirage against the same isolated fake-service tenant.
 * gh's HTTP socket setting keeps the native proxy local without a generated
 * certificate or platform-specific trust-store configuration.
 */
export async function searchConformance(endpoint: string): Promise<number> {
  const temp = await mkdtemp(join(tmpdir(), 'gh-conformance-'))
  const socket = join(temp, 'http.sock')
  await writeFile(join(temp, 'config.yml'), `http_unix_socket: ${socket}\n`)
  const nativeQueries: string[] = [],
    mirageQueries: string[] = [],
    failures: unknown[] = []
  async function forward(
    req: IncomingMessage,
    res: ServerResponse,
    queries: string[],
  ): Promise<void> {
    try {
      const { pathname, search, searchParams } = new URL(req.url ?? '/', 'http://proxy.invalid')
      if (pathname.includes('/search/')) queries.push(searchParams.get('q') ?? '')
      const chunks: Buffer[] = []
      for await (const chunk of req) chunks.push(chunk as Buffer)
      const response = await fetch(`${endpoint}${pathname}${search}`, {
        method: req.method ?? 'GET',
        headers: HEADERS,
        ...(chunks.length === 0 ? {} : { body: Buffer.concat(chunks) }),
      })
      res.writeHead(response.status, {
        ...Object.fromEntries(response.headers),
        'x-github-enterprise-version': '3.16.0',
      })
      res.end(Buffer.from(await response.arrayBuffer()))
    } catch (error) {
      failures.push(error)
      res.writeHead(502)
      res.end()
    }
  }
  const proxy = createHttpServer((req, res) => {
    void forward(req, res, nativeQueries)
  })
  const mirror = createHttpServer((req, res) => {
    void forward(req, res, mirageQueries)
  })
  await new Promise<void>((resolve) => proxy.listen(socket, resolve))
  await new Promise<void>((resolve) => mirror.listen(0, '127.0.0.1', resolve))
  const mirrorAddress = mirror.address()
  if (mirrorAddress === null || typeof mirrorAddress === 'string')
    throw new Error('missing proxy address')
  const base = `http://127.0.0.1:${mirrorAddress.port}`
  const ws = new Workspace(
    { '/scratch': new RAMVFS() },
    { mode: 'exec', clis: { gh: ['gh', { token: 'integ', base_url: base }] } },
  )
  try {
    const reset = await fetch(`${endpoint}/reset`, {
      method: 'POST',
      headers: HEADERS,
      body: JSON.stringify({ run: TENANT, tenants: ['default'], fixture: 'v1' }),
    })
    if (!reset.ok) throw new Error(`reset: ${await reset.text()}`)
    for (let i = 0; i < 105; i++) {
      const response = await fetch(`${endpoint}/repos/${REPO}/issues`, {
        method: 'POST',
        headers: HEADERS,
        body: JSON.stringify({
          title: `conformance ${i}`,
          body: 'search fixture',
          labels: ['bug'],
        }),
      })
      if (!response.ok) throw new Error(await response.text())
      if (i === 0) {
        const { number } = (await response.json()) as { number: number }
        const comment = await fetch(`${endpoint}/repos/${REPO}/issues/${number}/comments`, {
          method: 'POST',
          headers: HEADERS,
          body: JSON.stringify({ body: 'search fixture' }),
        })
        if (!comment.ok) throw new Error(await comment.text())
      }
    }
    // A pull request needs a head branch holding a commit its base lacks.
    const main = await fetch(`${endpoint}/repos/${REPO}/git/ref/heads/main`, { headers: HEADERS })
    if (!main.ok) throw new Error(await main.text())
    const { object } = (await main.json()) as { object: { sha: string } }
    for (const [path, body] of [
      ['git/refs', { ref: 'refs/heads/feature', sha: object.sha }],
      [
        'contents/FEATURE.md',
        { message: 'Add feature', content: 'ZmVhdHVyZQo=', branch: 'feature' },
      ],
    ] as const) {
      const made = await fetch(`${endpoint}/repos/${REPO}/${path}`, {
        method: path === 'git/refs' ? 'POST' : 'PUT',
        headers: HEADERS,
        body: JSON.stringify(body),
      })
      if (!made.ok) throw new Error(await made.text())
    }
    const pull = await fetch(`${endpoint}/repos/${REPO}/pulls`, {
      method: 'POST',
      headers: HEADERS,
      body: JSON.stringify({
        title: 'conformance pull',
        body: 'search fixture',
        head: 'feature',
        base: 'main',
        draft: true,
      }),
    })
    if (!pull.ok) throw new Error(await pull.text())
    const cases: string[][] = [
      [
        'issues',
        'conformance',
        '--repo',
        REPO,
        '--limit',
        '102',
        '--json',
        'number,title,repository,isPullRequest',
      ],
      [
        'issues',
        'conformance',
        '--repo',
        REPO,
        '--label',
        'bug',
        '--created',
        '2026-01-01',
        '--limit',
        '2',
        '--json',
        'assignees,author,authorAssociation,body,closedAt,commentsCount,createdAt,id,isLocked,isPullRequest,labels,number,repository,state,title,updatedAt,url',
      ],
      ['issues', 'conformance', '--repo', REPO, '--limit', '1'],
      [
        'issues',
        'conformance',
        '--repo',
        REPO,
        '--limit',
        '2',
        '--json',
        'title,number',
        '--jq',
        'map(.number)',
      ],
      [
        'issues',
        'conformance',
        '--repo',
        REPO,
        '--limit',
        '2',
        '--json',
        'number,title',
        '--template',
        '{{range .}}{{if .number}}{{printf "%v: %s\\n" .number .title}}{{end}}{{end}}',
      ],
      [
        'issues',
        'conformance',
        '--repo',
        REPO,
        '--include-prs',
        '--limit',
        '110',
        '--json',
        'isPullRequest',
        '--jq',
        'map(select(.isPullRequest)) | length',
      ],
      [
        'prs',
        '--repo',
        REPO,
        '--draft=true',
        '--json',
        'number,title,isDraft,isPullRequest,state,repository',
      ],
      ['prs', '--repo', REPO, '--draft=false', '--json', 'number'],
      [
        'repos',
        '--owner',
        'integ',
        '--limit',
        '1',
        '--json',
        'createdAt,defaultBranch,description,forksCount,fullName,hasDownloads,hasIssues,hasPages,hasProjects,hasWiki,homepage,id,isArchived,isDisabled,isFork,isPrivate,language,license,name,openIssuesCount,owner,pushedAt,size,stargazersCount,updatedAt,url,visibility,watchersCount',
      ],
      ['repos', '--owner', 'integ', '--limit', '1'],
      [
        'code',
        'import',
        '--repo',
        REPO,
        '--limit',
        '1',
        '--json',
        'path,repository,sha,textMatches,url',
      ],
      ['code', 'import', '--repo', REPO, '--limit', '1'],
      [
        'commits',
        '--repo',
        REPO,
        '--limit',
        '2',
        '--json',
        'author,commit,committer,id,parents,repository,sha,url',
      ],
      ['commits', '--repo', REPO, '--limit', '1'],
      [
        'issues',
        'conformance',
        '--repo',
        REPO,
        '--sort',
        'comments',
        '--limit',
        '2',
        '--json',
        'number,commentsCount',
      ],
      [
        'issues',
        'conformance',
        '--repo',
        REPO,
        '--limit',
        '2',
        '--json',
        'number,title',
        '--template',
        '{{range $i, $issue := .}}{{$i}}:{{$issue.number}} {{$issue.title}}{{"\\n"}}{{end}}',
      ],
      ['prs', '--repo', REPO, '--checks', 'success', '--json', 'number'],
      ['code', 'parse_step_1', '--repo', REPO],
    ]
    const env = {
      ...process.env,
      GH_HOST: 'github.example.test',
      GH_ENTERPRISE_TOKEN: 'integ',
      GH_CONFIG_DIR: temp,
      GH_PAGER: 'cat',
      NO_COLOR: '1',
    }
    cases.push(
      ['code', '--repo', REPO, '--json', 'path'],
      [
        'issues',
        'two words',
        '--repo',
        REPO,
        '--repo',
        'other/repo',
        '--label',
        'bug,help wanted',
        '--owner',
        'integ',
        '--archived=false',
        '--locked=false',
        '--no-assignee',
        '--match',
        'title,body',
        '--visibility',
        'public',
        '--sort',
        'updated',
        '--order',
        'asc',
        '--json',
        'number',
      ],
      [
        'prs',
        '--repo',
        REPO,
        '--base',
        'main',
        '--head',
        'feature',
        '--checks',
        'success',
        '--merged=false',
        '--merged-at',
        '>2025-01-01',
        '--review',
        'required',
        '--review-requested',
        'integ/team',
        '--reviewed-by',
        'person',
        '--app',
        'bot',
        '--json',
        'number',
      ],
      [
        'repos',
        '--owner',
        'integ,other',
        '--language',
        'TypeScript',
        '--license',
        'mit,apache-2.0',
        '--topic',
        'agent,terminal',
        '--include-forks',
        'only',
        '--number-topics',
        '>2',
        '--stars',
        '>5',
        '--archived=false',
        '--json',
        'name',
      ],
      [
        'code',
        'two words',
        '--repo',
        REPO,
        '--owner',
        'integ',
        '--extension',
        'ts',
        '--filename',
        'main.ts',
        '--language',
        'TypeScript',
        '--match',
        'file',
        '--size',
        '>10',
        '--json',
        'path',
      ],
      [
        'commits',
        '--repo',
        REPO,
        '--author-name',
        'A Person',
        '--author-email',
        'a@example.test',
        '--committer',
        'person',
        '--merge=false',
        '--parent',
        'abc',
        '--tree',
        'def',
        '--visibility',
        'public',
        '--author-date',
        '>2025-01-01',
        '--json',
        'sha',
      ],
    )
    cases.push(
      ['issues', 'needle', '--repo', 'integ/missing'],
      ['prs', 'needle', '--repo', 'integ/missing'],
      ['code', 'needle', '--repo', 'integ/missing', '--json', 'path'],
      ['commits', 'needle', '--repo', 'integ/missing'],
    )
    const commands = cases.map((args) => ['search', ...args])
    commands.push(
      ['api', 'repos/integ/missing'],
      ['api', 'repos/integ/missing', '--silent'],
      ['api', 'repos/integ/missing', '--jq', '.message'],
      ['api', 'repos/integ/missing', '--paginate'],
      ['api', 'repos/integ/missing', '--paginate', '--slurp'],
      ['api', 'search/issues?q=repo:integ/missing'],
      ['api', 'graphql', '-f', `query=${MISSING_REPO_QUERY}`],
      ['api', 'graphql', '-f', `query=${MISSING_REPO_QUERY}`, '--jq', '.data'],
      ['api', 'graphql', '-f', 'query={ viewer { bogus } }'],
      ['api', 'graphql', '-f', 'query={ viewer { login } }', '--jq', '.data.viewer.login'],
    )
    for (const args of commands) {
      nativeQueries.length = 0
      mirageQueries.length = 0
      const native = await run('gh', args, env)
      const line = ['gh', ...args].map((word) => `'${word.replaceAll("'", "'\\''")}'`).join(' ')
      const result = await ws.shell(line)
      if (failures.length > 0) throw new Error(line, { cause: failures[0] })
      if (nativeQueries[0] !== mirageQueries[0])
        throw new Error(
          `${line}\nquery native: ${nativeQueries[0]}\nquery mirage: ${mirageQueries[0]}\nnative ${native.code}: ${native.stderr}`,
        )
      const stdout = new TextDecoder().decode(result.stdout),
        stderr = new TextDecoder().decode(result.stderr)
      const json = args.includes('--json') && !args.includes('--jq') && !args.includes('--template')
      const same =
        json && result.exitCode === 0 && native.code === 0
          ? isDeepStrictEqual(JSON.parse(stdout), JSON.parse(native.stdout))
          : stdout === native.stdout
      if (result.exitCode !== native.code || !same || stderr !== native.stderr)
        throw new Error(
          `${line}\nnative ${native.code}: ${native.stdout}${native.stderr}\nmirage ${result.exitCode}: ${stdout}${stderr}`,
        )
    }
    return commands.length
  } finally {
    await ws.close()
    await new Promise<void>((resolve, reject) =>
      proxy.close((error) => (error ? reject(error) : resolve())),
    )
    await new Promise<void>((resolve, reject) =>
      mirror.close((error) => (error ? reject(error) : resolve())),
    )
    await rm(temp, { recursive: true, force: true })
  }
}
