import { parseFlags, truncateGeneric } from '../../generic/truncate.ts'
import { type Builder, requireOp, resolveGlobOf } from '../adapter.ts'

export const BUILDER: Builder = {
  name: 'truncate',
  write: true,
  fn: async (ops, accessor, paths, _texts, opts) => {
    const flags = parseFlags(opts.flags)
    const truncate = requireOp(ops.truncate, 'truncate')
    const index = opts.index ?? undefined
    const resolved = await resolveGlobOf(ops)(accessor, paths, index)
    return truncateGeneric(
      resolved,
      flags,
      (path) => ops.stat(accessor, path, index),
      (path, length, noCreate) => truncate(accessor, path, length, noCreate),
    )
  },
}
