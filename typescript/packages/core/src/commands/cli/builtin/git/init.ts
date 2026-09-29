import { IOResult } from '../../../../io/types.ts'
import { FileType } from '../../../../types.ts'
import { resolvePath } from '../../../../utils/path.ts'
import type { CommandFnResult } from '../../../config.ts'
import { FlagView } from '../../../spec/flag_view.ts'
import type { CLIInvocation } from '../../types.ts'
import { discover } from './discover.ts'
import { GitError, NoWorkspaceError, NoWorkingDirectoryError } from './errors.ts'
import { ensureDir, readOptional, under, writeFile } from './io.ts'
import { validRefName } from './refs.ts'
import { fatal, startPoint } from './util.ts'

/** Initialize through the dispatcher; no host templates, hooks or branch advisory. */
export async function init(inv: CLIInvocation): Promise<CommandFnResult> {
  const fl = new FlagView(inv.flags)
  const doors = inv.doors ?? {}
  try {
    if (
      doors.dispatch === undefined ||
      doors.statPath === undefined ||
      doors.ns?.mounts === undefined
    )
      throw new NoWorkspaceError()
    const dispatch = doors.dispatch
    const mounts = doors.ns.mounts
    const start = startPoint(fl)
    const here = await doors.statPath(start)
    if (here?.type !== FileType.DIRECTORY)
      throw new NoWorkingDirectoryError(
        start,
        here === null ? 'No such file or directory' : 'Not a directory',
      )
    const target = resolvePath(inv.texts[0] ?? '.', start)
    const bare = fl.asBool('bare')
    const explicit = fl.asStr('git_dir')
    let gitdir =
      explicit === undefined
        ? bare
          ? target
          : under(target, '.git')
        : resolvePath(explicit, start)
    const branch = fl.asStr('initial_branch') ?? 'master'
    if (!validRefName(`refs/heads/${branch}`) || branch.startsWith('-'))
      throw new GitError(`invalid branch name: '${branch}'`)
    const info = await doors.statPath(gitdir)
    if (
      info !== null &&
      (info.type !== FileType.DIRECTORY ||
        (await readOptional(dispatch, under(gitdir, 'HEAD'))) !== null)
    ) {
      const location = await discover(
        dispatch,
        doors.statPath,
        (path) => mounts.rootOf(path),
        target,
        gitdir,
        fl.asStr('work_tree') ?? null,
      )
      gitdir = location.commondir
    }
    const existing = (await readOptional(dispatch, under(gitdir, 'HEAD'))) !== null
    for (const directory of ['objects/info', 'objects/pack', 'refs/heads', 'refs/tags', 'info'])
      await ensureDir(dispatch, under(gitdir, directory))
    const files = {
      HEAD: `ref: refs/heads/${branch}\n`,
      config: `[core]\n\trepositoryformatversion = 0\n\tfilemode = true\n\tbare = ${bare ? 'true' : 'false'}\n`,
      description: "Unnamed repository; edit this file 'description' to name the repository.\n",
    }
    for (const [name, text] of Object.entries(files)) {
      const path = under(gitdir, name)
      if ((await readOptional(dispatch, path)) === null)
        await writeFile(dispatch, path, new TextEncoder().encode(text))
    }
    const text = existing
      ? `Reinitialized existing Git repository in ${gitdir}/\n`
      : `Initialized empty Git repository in ${gitdir}/\n`
    const warning =
      existing && fl.asStr('initial_branch')
        ? `warning: re-init: ignored --initial-branch=${branch}\n`
        : ''
    return [
      new TextEncoder().encode(fl.asBool('quiet') ? '' : text),
      new IOResult({ stderr: new TextEncoder().encode(warning) }),
    ]
  } catch (err) {
    if (err instanceof GitError) return fatal(err)
    throw err
  }
}
