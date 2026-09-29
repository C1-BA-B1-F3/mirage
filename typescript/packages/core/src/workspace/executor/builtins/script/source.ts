// ========= Copyright 2026 @ Strukto.AI All Rights Reserved. =========
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.
// ========= Copyright 2026 @ Strukto.AI All Rights Reserved. =========

import type { ByteSource } from '../../../../io/types.ts'
import type { PathSpec } from '../../../../types.ts'
import { fsStrerror } from '../../../../utils/errors.ts'
import type { CallStack } from '../../../../shell/call_stack.ts'
import type { SessionState } from '../../../session/session.ts'
import { positionalParams, setPositionalParams } from '../../../session/state.ts'
import { ExecutionNode } from '../../../types.ts'
import type { DispatchFn } from '../../../../runtime/types.ts'
import { scopePath } from '../scope.ts'
import { SOURCE_USAGE } from './constants.ts'
import { readScriptText, scriptError } from './script.ts'
import type { BuiltinCall, ExecuteStringFn, Result } from '../types.ts'
import { wordText } from '../../../../types.ts'

export async function handleSource(
  dispatch: DispatchFn,
  executeFn: ExecuteStringFn,
  path: string | PathSpec,
  session: SessionState,
  args: string[] = [],
  stdin: ByteSource | null = null,
  callStack: CallStack | null = null,
): Promise<Result> {
  const raw = scopePath(path)
  if (wordText(path) === '') {
    // The empty name is a filename bash tries to open, not a missing
    // argument, so it fails like any file that is not there.
    return scriptError('source', ': No such file or directory', 1, 'source ')
  }
  let script: string
  try {
    script = await readScriptText(dispatch, raw, session.cwd)
  } catch (err) {
    const strerror = fsStrerror(err)
    if (strerror === null) throw err
    return scriptError('source', `${raw}: ${strerror}`, 1, `source ${raw}`)
  }
  // The file runs as a line of its own, which reads the shell's
  // parameters, so the ones in scope stand in for them while it runs.
  const shellParams = session.positionalArgs
  session.positionalArgs = args.length > 0 ? args : positionalParams(session, callStack)
  session.sourceDepth += 1
  try {
    const io = await executeFn(script, { sessionId: session.sessionId, stdin })
    return [io.stdout, io, new ExecutionNode({ command: `source ${raw}`, exitCode: io.exitCode })]
  } finally {
    session.sourceDepth -= 1
    const scoped = session.positionalArgs
    session.positionalArgs = shellParams
    if (args.length === 0) setPositionalParams(session, callStack, scoped)
  }
}

/**
 * The `source` / `.` arm. Positional parameters keep the words as typed,
 * so a path operand contributes its spelling, not its resolved mount path.
 */
export async function sourceBuiltin(call: BuiltinCall): Promise<Result> {
  const operands = [...call.argv.operands]
  const target = operands[0]
  if (target === undefined) return scriptError('source', SOURCE_USAGE, 2)
  const sourceArgs = operands.slice(1).map((o) => wordText(o))
  return handleSource(
    call.dispatch,
    call.executeFn,
    target,
    call.session,
    sourceArgs,
    call.stdin,
    call.callStack,
  )
}
