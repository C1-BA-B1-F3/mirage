import { GitHubApiError } from '../../../../core/github/client.ts'
import type { GhConfig } from '../../../../core/github/config.ts'
import { login } from '../../../../core/github/repo.ts'
import { IOResult } from '../../../../io/types.ts'
import type { CommandFnResult } from '../../../config.ts'
import type { CLIInvocation } from '../../types.ts'
import { ghTransport } from './accessor.ts'

/** Check the resolved config secret, whose original environment/file source is not retained. */
export async function status(inv: CLIInvocation): Promise<CommandFnResult> {
  const config = inv.config as GhConfig
  let host = new URL(config.baseUrl ?? 'https://github.com').hostname
  if (host === 'api.github.com') host = 'github.com'
  let account: string
  try {
    account = await login(ghTransport(config))
  } catch (err) {
    if (!(err instanceof GitHubApiError) || ![401, 403].includes(err.status)) throw err
    return [
      null,
      new IOResult({
        exitCode: 1,
        stderr: new TextEncoder().encode(
          `${host}\n  X Failed to log in using the token in Mirage configuration (HTTP ${String(err.status)})\n`,
        ),
      }),
    ]
  }
  if (account === '')
    return [
      null,
      new IOResult({
        exitCode: 1,
        stderr: new TextEncoder().encode(`${host}: authenticated response has no login\n`),
      }),
    ]
  return [
    new TextEncoder().encode(
      `${host}\n  ✓ Logged in to ${host} account ${account} (Mirage configuration)\n  - Active account: true\n`,
    ),
    new IOResult(),
  ]
}
