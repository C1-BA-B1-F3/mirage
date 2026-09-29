import git from 'isomorphic-git'
import { IOResult } from '../../../../io/types.ts'
import { fnmatch } from '../../../../utils/fnmatch.ts'
import { compareCodePoints } from '../../../../utils/sort.ts'
import type { CommandFnResult } from '../../../config.ts'
import { FlagView } from '../../../spec/flag_view.ts'
import type { CLIInvocation } from '../../types.ts'
import { GitError } from './errors.ts'
import { loadRefs } from './refs.ts'
import { opened, repoArgs } from './repo.ts'
import { fatal } from './util.ts'
import { resolveObject } from './revparse.ts'

export async function forEachRef(inv: CLIInvocation): Promise<CommandFnResult> {
  const fl = new FlagView(inv.flags)
  try {
    const count = fl.asInt('count') ?? 0
    if (count < 0) throw new GitError(`invalid --count argument: ${String(count)}`)
    const repo = await opened(fl, inv.doors ?? {})
    const refs = await loadRefs(repo.dispatch, repo.location.gitdir, repo.location.commondir)
    const template = fl.asStr('format') ?? '%(objectname) %(objecttype)\t%(refname)'
    const rows: string[] = []
    for (const name of [...refs.keys()]
      .filter((ref) => ref.startsWith('refs/'))
      .sort(compareCodePoints)) {
      if (
        inv.texts.length &&
        !inv.texts.some(
          (p) => name === p || name.startsWith(p.replace(/\/$/, '') + '/') || fnmatch(name, p),
        )
      )
        continue
      const oid = await git.resolveRef({ ...repoArgs(repo), ref: name })
      const obj = await resolveObject(repo, oid)
      let message = ''
      if (obj.type === 'commit')
        message = (await git.readCommit({ ...repoArgs(repo), oid })).commit.message
      if (obj.type === 'tag') message = (await git.readTag({ ...repoArgs(repo), oid })).tag.message
      const atoms: Record<string, string> = {
        refname: name,
        'refname:short': name.replace(/^refs\/(heads|tags|remotes)\//, ''),
        objectname: oid,
        'objectname:short': oid.slice(0, repo.abbrev),
        objecttype: obj.type,
        subject: (message.split('\n\n')[0] ?? '').trimEnd().replaceAll('\n', ' '),
        contents: message,
      }
      rows.push(
        template.replace(
          /%\(([^)]+)\)|%([0-9a-fA-F]{2})/g,
          (_match, atom: string | undefined, hex: string | undefined) => {
            if (atom === undefined) return String.fromCharCode(parseInt(hex ?? '0', 16))
            if (!(atom in atoms)) throw new GitError(`unknown field name: ${atom}`)
            return atoms[atom] ?? ''
          },
        ) + '\n',
      )
      if (count && rows.length >= count) break
    }
    return [new TextEncoder().encode(rows.join('')), new IOResult()]
  } catch (err) {
    if (err instanceof GitError) return fatal(err)
    throw err
  }
}
