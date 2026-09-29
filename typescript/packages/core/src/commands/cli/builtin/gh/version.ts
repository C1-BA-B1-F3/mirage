import type { CommandFnResult } from '../../../config.ts'
import type { CLIInvocation } from '../../types.ts'
import { IOResult } from '../../../../io/types.ts'
import { VERSION } from '../../../../version.ts'

/** Report Mirage's package version instead of an upstream gh build and release URL. */
export function version(_inv: CLIInvocation): CommandFnResult {
  return [new TextEncoder().encode(`gh version ${VERSION} (Mirage)\n`), new IOResult()]
}
