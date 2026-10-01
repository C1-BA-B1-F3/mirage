import { readHead, loadRefs } from './refs.ts'
import git from 'isomorphic-git'
import { VERSION } from '../../../../version.ts'

import { compilePosixRegex } from '../../../../utils/posix.ts'
import { BreError, PosixSyntax, translateEre } from '../../../builtin/utils/bre.ts'
import { compareCodePoints } from '../../../../utils/sort.ts'
import { IOResult } from '../../../../io/types.ts'
import type { CommandFnResult } from '../../../config.ts'
import { FlagView } from '../../../spec/flag_view.ts'
import type { CLIInvocation } from '../../types.ts'
import { GitError, NoWorkspaceError } from './errors.ts'
import { parseFlags, refCommits, select } from './history.ts'
import { repoArgs } from './repo.ts'
import { opened } from './session.ts'
import { configLines } from './fs.ts'
import { readFile, readOptional } from './io.ts'
import { splitRevisions, resolveObject } from './revparse.ts'
import { checkOperands, escaped, fatal, startPoint } from './util.ts'

const ENC = new TextEncoder()
const SHOW_TOPLEVEL = '--show-toplevel'

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

/**
 * The per-user config files `--global` reads, in git's order.
 *
 * `$GIT_CONFIG_GLOBAL` alone when set, else the XDG file then `~/.gitconfig`,
 * each read through the dispatcher from the session's own `HOME` so the answer
 * is the workspace's and never the host's. Only `--list` refuses when neither
 * exists.
 */
export async function globalSources(
  inv: CLIInvocation,
  listing: boolean,
): Promise<{ source: string; data: Uint8Array }[]> {
  const dispatch = inv.doors?.dispatch
  if (!dispatch) throw new NoWorkspaceError()
  const home = inv.env.HOME ?? ''
  const override = inv.env.GIT_CONFIG_GLOBAL
  if (override === undefined && !home) throw new GitError('$HOME not set')
  const target = override ?? `${home}/.gitconfig`
  const configured = inv.env.XDG_CONFIG_HOME ?? ''
  const xdg = configured === '' ? `${home}/.config` : configured
  const sources: { source: string; data: Uint8Array }[] = []
  for (const source of override === undefined ? [`${xdg}/git/config`, target] : [target]) {
    const data = await readOptional(dispatch, source)
    if (data !== null) sources.push({ source, data })
  }
  if (!sources.length && listing)
    throw new GitError(`unable to read config file '${target}': No such file or directory`)
  return sources
}

export async function config(inv: CLIInvocation): Promise<CommandFnResult> {
  const fl = new FlagView(inv.flags)
  try {
    let sources: { source: string; data: Uint8Array }[]
    if (fl.asBool('global')) sources = await globalSources(inv, fl.asBool('list'))
    else {
      const repo = await opened(fl, inv.doors ?? {})
      const path = `${repo.location.commondir}/config`
      const ordinary =
        repo.location.commondir === repo.location.worktree + '/.git' &&
        startPoint(fl) === repo.location.worktree
      sources = [
        { source: ordinary ? '.git/config' : path, data: await readFile(repo.dispatch, path) },
      ]
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
      pattern = regexp
        ? compilePosixRegex(translateEre(configKey(key), PosixSyntax.EXTENDED)[0])
        : null
    } catch (err) {
      if (!(err instanceof SyntaxError) && !(err instanceof BreError)) throw err
      return [
        null,
        new IOResult({ exitCode: 6, stderr: ENC.encode(`error: invalid key pattern: ${key}\n`) }),
      ]
    }
    const values: [string, string, string][] = []
    for (const { source, data } of sources) {
      for (const line of await configLines(new TextDecoder().decode(data))) {
        if (listing || (pattern ? pattern.test(line.path) : line.path === configKey(key)))
          values.push([source, line.path, line.value ?? ''])
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
/**
 * How many revisions rev-parse prints ahead of one of its options.
 *
 * rev-parse answers its arguments in line order, so `HEAD --show-toplevel`
 * prints the id first. Every word after the option that is not a dash word is
 * one of the later revisions.
 */
function revisionsBefore(argv: readonly string[], count: number, option: string): number {
  const at = argv.indexOf(option)
  if (at < 0) return 0
  return count - argv.slice(at + 1).filter((word) => !word.startsWith('-')).length
}

export async function revParse(inv: CLIInvocation): Promise<CommandFnResult> {
  const fl = new FlagView(inv.flags)
  try {
    checkOperands(inv.texts, undefined, escaped(inv.argv))
    const toplevel = fl.asBool('show_toplevel')
    const repo = await opened(fl, inv.doors ?? {}, toplevel)
    const head = await readHead(repo.dispatch, repo.location.gitdir)
    const refs = await loadRefs(repo.dispatch, repo.location.gitdir, repo.location.commondir)
    const rows: string[] = []
    for (const revision of inv.texts) {
      const obj = await resolveObject(repo, revision)
      if (!fl.asBool('abbrev_ref')) {
        rows.push(obj.oid + '\n')
        continue
      }
      if (revision === 'HEAD') {
        rows.push((head.ref?.replace(/^refs\/heads\//, '') ?? 'HEAD') + '\n')
        continue
      }
      const name = [
        revision,
        'refs/' + revision,
        'refs/tags/' + revision,
        'refs/heads/' + revision,
        'refs/remotes/' + revision,
      ].find((name) => refs.has(name))
      rows.push(name === undefined ? '' : name.replace(/^refs\/(heads|tags|remotes)\//, '') + '\n')
    }
    if (toplevel)
      rows.splice(
        revisionsBefore(inv.argv, rows.length, SHOW_TOPLEVEL),
        0,
        `${repo.location.worktree}\n`,
      )
    return [ENC.encode(rows.join('')), new IOResult()]
  } catch (err) {
    if (err instanceof GitError) return fatal(err)
    throw err
  }
}
