import { IOResult } from '../../../../io/types.ts'
import { encodeText } from '../../../../shell/bytes.ts'
import { compareCodePoints } from '../../../../utils/sort.ts'
import type { CommandFnResult } from '../../../config.ts'
import { FlagView } from '../../../spec/flag_view.ts'
import type { CLIInvocation } from '../../types.ts'
import { GitError } from './errors.ts'
import { readIndex } from './index_file.ts'
import { repoRelative } from './pathspec.ts'
import { quotePath } from './render.ts'
import { configBool, opened } from './repo.ts'
import { fatal, startPoint } from './util.ts'
import { fnmatch } from '../../../../utils/fnmatch.ts'

export async function lsFiles(inv: CLIInvocation): Promise<CommandFnResult> {
  const fl = new FlagView(inv.flags)
  try {
    const repo = await opened(fl, inv.doors ?? {})
    const fully = await configBool(repo, 'core.quotepath', true)
    const state = await readIndex(repo, repo.dispatch)
    const prefix = repoRelative(repo.location, startPoint(fl), '.')
    const patterns = inv.texts.map((text) => repoRelative(repo.location, startPoint(fl), text))
    const rows = [...state.entries.values()]
    for (const conflict of state.conflicts.values()) {
      for (const entry of [conflict.ancestor, conflict.this, conflict.other])
        if (entry) rows.push(entry)
    }
    rows.sort((a, b) => compareCodePoints(a.path, b.path) || a.stage - b.stage)
    let out = ''
    for (const entry of rows) {
      const name = entry.path
      if (prefix && !name.startsWith(prefix + '/')) continue
      if (
        patterns.length &&
        !patterns.some(
          (pattern) =>
            !pattern ||
            name === pattern ||
            name.startsWith(pattern + '/') ||
            fnmatch(name, pattern),
        )
      )
        continue
      const relative = prefix ? name.slice(prefix.length + 1) : name
      const label = fl.asBool('z') ? relative : quotePath(relative, false, fully)
      const metadata = fl.asBool('stage')
        ? `${entry.mode.toString(8).padStart(6, '0')} ${entry.oid} ${String(entry.stage)}\t`
        : ''
      out += metadata + label + (fl.asBool('z') ? '\0' : '\n')
    }
    return [encodeText(out), new IOResult()]
  } catch (err) {
    if (err instanceof GitError) return fatal(err)
    throw err
  }
}
