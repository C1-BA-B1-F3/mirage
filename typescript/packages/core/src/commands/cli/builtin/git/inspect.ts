import { readHead, loadRefs } from './refs.ts'
import git from 'isomorphic-git'
import { GitConfigManager } from 'isomorphic-git/managers'
import { VERSION } from '../../../../version.ts'

import { translateClasses } from '../../../../utils/posix.ts'
import { compareCodePoints } from '../../../../utils/sort.ts'
import { IOResult } from '../../../../io/types.ts'
import type { CommandFnResult } from '../../../config.ts'
import { FlagView } from '../../../spec/flag_view.ts'
import type { CLIInvocation } from '../../types.ts'
import { GitError, NoWorkspaceError } from './errors.ts'
import { parseFlags, refCommits, select } from './history.ts'
import { opened, repoArgs } from './repo.ts'
import { readFile, readOptional } from './io.ts'
import { splitRevisions, resolveObject } from './revparse.ts'
import { checkOperands, escaped, fatal, startPoint } from './util.ts'

const ENC = new TextEncoder()

export async function remote(inv: CLIInvocation): Promise<CommandFnResult> {
  const fl = new FlagView(inv.flags)
  try {
    checkOperands([...inv.texts], undefined, escaped(inv.argv))
    const repo = await opened(fl, inv.doors ?? {})
    const rows = (await git.listRemotes(repoArgs(repo))).sort((a, b) =>
      compareCodePoints(a.remote, b.remote),
    )
    const lines: string[] = []
    for (const row of rows) {
      if (!fl.asBool('verbose')) lines.push(row.remote)
      else {
        const urls = (await git.getConfigAll({
          ...repoArgs(repo),
          path: `remote.${row.remote}.url`,
        })) as string[]
        const push = (await git.getConfigAll({
          ...repoArgs(repo),
          path: `remote.${row.remote}.pushurl`,
        })) as string[]
        if (urls[0]) lines.push(`${row.remote}\t${urls[0]} (fetch)`)
        for (const url of push.length ? push : urls) lines.push(`${row.remote}\t${url} (push)`)
      }
    }
    return [ENC.encode(lines.length ? `${lines.join('\n')}\n` : ''), new IOResult()]
  } catch (err) {
    if (err instanceof GitError) return fatal(err)
    throw err
  }
}

export async function config(inv: CLIInvocation): Promise<CommandFnResult> {
  const fl = new FlagView(inv.flags)
  try {
    const sources: { source: string; data: Uint8Array }[] = []
    if (fl.asBool('global')) {
      const dispatch = inv.doors?.dispatch
      if (!dispatch) throw new NoWorkspaceError()
      const home = inv.env.HOME ?? ''
      const override = inv.env.GIT_CONFIG_GLOBAL
      if (override === undefined && !home) throw new GitError('$HOME not set')
      const target = override ?? `${home}/.gitconfig`
      const configuredXdg = inv.env.XDG_CONFIG_HOME ?? ''
      const xdg = configuredXdg === '' ? `${home}/.config` : configuredXdg
      for (const source of override === undefined ? [`${xdg}/git/config`, target] : [target]) {
        const data = await readOptional(dispatch, source)
        if (data !== null) sources.push({ source, data })
      }
      if (!sources.length && fl.asBool('list'))
        throw new GitError(`unable to read config file '${target}': No such file or directory`)
    } else {
      const repo = await opened(fl, inv.doors ?? {})
      const source =
        repo.location.commondir === repo.location.worktree + '/.git' &&
        startPoint(fl) === repo.location.worktree
          ? '.git/config'
          : repo.location.commondir + '/config'
      sources.push({
        source,
        data: await readFile(repo.dispatch, `${repo.location.commondir}/config`),
      })
    }
    const listing = fl.asBool('list'),
      regexp = fl.asBool('get_regexp'),
      origin = fl.asBool('show_origin')
    if (!listing && !inv.texts.length)
      return [
        null,
        new IOResult({ exitCode: 129, stderr: ENC.encode('error: wrong number of arguments\n') }),
      ]
    const key = inv.texts[0] ?? ''
    let pattern: RegExp | null
    try {
      pattern = regexp ? new RegExp(translateClasses(configKey(key))) : null
    } catch (err) {
      if (!(err instanceof SyntaxError)) throw err
      return [
        null,
        new IOResult({ exitCode: 6, stderr: ENC.encode(`error: invalid key pattern: ${key}\n`) }),
      ]
    }
    const values: [string, string, string][] = []
    for (const { source, data } of sources) {
      const text = new TextDecoder().decode(data)
      const parsed = await GitConfigManager.get({
        fs: { read: () => Promise.resolve(text) } as never,
        gitdir: '/',
      })
      let section = ''
      const keys: string[] = []
      for (const line of text.split('\n')) {
        const header = /^\s*\[([\w.-]+)(?:\s+"((?:[^"\\]|\\.)*)")?\]/.exec(line)
        if (header) {
          section =
            (header[1] ?? '').toLowerCase() +
            (header[2] === undefined ? '' : '.' + header[2].replace(/\\(.)/g, '$1'))
          continue
        }
        const entry = /^\s*([\w-]+)\s*(?:=|$)/.exec(line)
        if (entry && section) keys.push(section + '.' + (entry[1] ?? '').toLowerCase())
      }
      const seen = new Map<string, number>(),
        cache = new Map<string, (string | boolean)[]>()
      for (const name of keys) {
        const at = seen.get(name) ?? 0
        seen.set(name, at + 1)
        if (!(listing || (pattern ? pattern.test(name) : name === configKey(key)))) continue
        let held = cache.get(name)
        if (!held) {
          held = (await parsed.getall(name)) as (string | boolean)[]
          cache.set(name, held)
        }
        values.push([source, name, String(held[at] ?? '')])
      }
    }
    const chosen = listing || regexp ? values : values.slice(-1)
    const out = chosen
      .map(
        ([source, name, value]) =>
          (origin ? `file:${source}\t` : '') +
          (listing || regexp ? name + (listing ? '=' : ' ') : '') +
          value +
          '\n',
      )
      .join('')
    return [ENC.encode(out), new IOResult({ exitCode: chosen.length || listing ? 0 : 1 })]
  } catch (err) {
    if (err instanceof GitError) return fatal(err)
    throw err
  }
}

export async function showRef(inv: CLIInvocation): Promise<CommandFnResult> {
  const fl = new FlagView(inv.flags)
  try {
    const repo = await opened(fl, inv.doors ?? {})
    const refs = await loadRefs(repo.dispatch, repo.location.gitdir, repo.location.commondir)
    const lines: string[] = []
    for (const ref of [...refs.keys()]
      .filter((r) => r.startsWith('refs/'))
      .sort(compareCodePoints)) {
      if (
        inv.texts.length &&
        !inv.texts.some((pattern) => ref === pattern || ref.endsWith(`/${pattern}`))
      )
        continue
      const oid = await git.resolveRef({ ...repoArgs(repo), ref })
      lines.push(`${oid} ${ref}`)
    }
    return [
      ENC.encode(lines.length ? `${lines.join('\n')}\n` : ''),
      new IOResult({ exitCode: lines.length ? 0 : 1 }),
    ]
  } catch (err) {
    if (err instanceof GitError) return fatal(err)
    throw err
  }
}

export async function revList(inv: CLIInvocation): Promise<CommandFnResult> {
  const fl = new FlagView(inv.flags)
  try {
    checkOperands([...inv.texts], undefined, escaped(inv.argv))
    const repo = await opened(fl, inv.doors ?? {})
    const flags = parseFlags(fl)
    if (!inv.texts.length && !flags.allRefs)
      return [
        null,
        new IOResult({
          exitCode: 129,
          stderr: ENC.encode('usage: git rev-list [<options>] <commit>...\n'),
        }),
      ]
    const [shown, hidden] = await splitRevisions(repo, inv.texts)
    const starts = flags.allRefs ? [...(await refCommits(repo)), ...shown] : shown
    const commits = await select(repo, starts, flags, hidden)
    const out = fl.asBool('count')
      ? `${String(commits.length)}\n`
      : commits.map((c) => `${c.oid}\n`).join('')
    return [ENC.encode(out), new IOResult()]
  } catch (err) {
    if (err instanceof GitError) return fatal(err)
    throw err
  }
}

export function version(_inv: CLIInvocation): CommandFnResult {
  return [ENC.encode(`git version ${VERSION} (Mirage)\n`), new IOResult()]
}

function configKey(key: string): string {
  const parts = key.split('.')
  return parts
    .map((part, i) => (i === 0 || i === parts.length - 1 ? part.toLowerCase() : part))
    .join('.')
}

/** Resolve object ids or abbreviated symbolic reference names. */
export async function revParse(inv: CLIInvocation): Promise<CommandFnResult> {
  const fl = new FlagView(inv.flags)
  try {
    checkOperands(inv.texts, undefined, escaped(inv.argv))
    const repo = await opened(fl, inv.doors ?? {}, fl.asBool('show_toplevel'))
    const head = await readHead(repo.dispatch, repo.location.gitdir)
    const refs = await loadRefs(repo.dispatch, repo.location.gitdir, repo.location.commondir)
    let out = fl.asBool('show_toplevel') ? repo.location.worktree + '\n' : ''
    for (const revision of inv.texts) {
      const obj = await resolveObject(repo, revision)
      if (!fl.asBool('abbrev_ref')) {
        out += obj.oid + '\n'
        continue
      }
      if (revision === 'HEAD') {
        out += (head.ref?.replace(/^refs\/heads\//, '') ?? 'HEAD') + '\n'
        continue
      }
      const name = [
        revision,
        'refs/' + revision,
        'refs/tags/' + revision,
        'refs/heads/' + revision,
        'refs/remotes/' + revision,
      ].find((name) => refs.has(name))
      if (name !== undefined) out += name.replace(/^refs\/(heads|tags|remotes)\//, '') + '\n'
    }
    return [new TextEncoder().encode(out), new IOResult()]
  } catch (err) {
    if (err instanceof GitError) return fatal(err)
    throw err
  }
}
