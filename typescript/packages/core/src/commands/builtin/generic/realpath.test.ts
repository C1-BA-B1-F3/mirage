import { expect, it } from 'vitest'
import realpathCases from '../../../../../../../integ/unix/realpath/error.json' with { type: 'json' }
import nestedCases from '../../../../../../../integ/crossmount/nested/basic.json' with { type: 'json' }
import { MountMode } from '../../../types.ts'
import { RAMVFS } from '../../../vfs/ram/ram.ts'
import { runResult } from '../../../workspace/fixtures/integration_fixture.ts'
import { getTestParser } from '../../../workspace/fixtures/workspace_fixture.ts'
import { Workspace } from '../../../workspace/workspace/workspace.ts'

it.each([
  ...realpathCases.cases.filter((case_) => case_.id.startsWith('realpath_review_')),
  ...nestedCases.cases.filter((case_) => case_.id.startsWith('nest_realpath_')),
])('$id', async (case_) => {
  const mounts: Record<string, RAMVFS> = { '/data': new RAMVFS() }
  if (case_.targets.includes('ram-nested')) mounts['/data/inner'] = new RAMVFS()
  const ws = new Workspace(mounts, {
    mode: MountMode.WRITE,
    shellParser: await getTestParser(),
  })
  try {
    expect(await runResult(ws, case_.command)).toEqual([
      case_.expect.exit,
      case_.expect.stdout,
      case_.expect.stderr,
    ])
  } finally {
    await ws.close()
  }
})
