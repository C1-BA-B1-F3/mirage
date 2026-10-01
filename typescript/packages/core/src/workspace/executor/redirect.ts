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

import { runWithRedirectPaths } from '../../context/session_context.ts'
import { fsStrerror, isFsError, isMissingPath } from '../../utils/errors.ts'
import { stripSlash } from '../../utils/slash.ts'
import { SharedInput, share } from '../../io/async_line_iterator.ts'
import type { ByteSource } from '../../io/types.ts'
import { DeviceInput, IOResult, materialize } from '../../io/types.ts'
import { encodeText } from '../../shell/bytes.ts'
import type { CallStack } from '../../shell/call_stack.ts'
import { FD_BOTH, FD_CLOSE, FD_STDERR, FD_STDIN, FD_STDOUT } from '../../shell/constants.ts'
import {
  FileDescription,
  FileInput,
  type Descriptor,
  badDescriptorLine,
  unreadableStdin,
  unsupportedDescriptor,
} from '../../shell/descriptors.ts'
import { getText } from '../../shell/helpers.ts'
import { type Redirect, RedirectKind } from '../../shell/types.ts'
import { FileStat, FileType, PathSpec } from '../../types.ts'
import type { TSNodeLike } from '../../shell/types.ts'
import type { SessionState } from '../session/session.ts'
import { ExecutionNode } from '../types.ts'
import type { DispatchFn } from '../../runtime/types.ts'
import { writeDescription } from './create.ts'
import {
  CLOSED as EXEC_CLOSED,
  OPEN_FOR_READING,
  TO_STDERR as EXEC_TO_STDERR,
  TO_STDIN as EXEC_TO_STDIN,
  TO_STDOUT as EXEC_TO_STDOUT,
} from './builtins/exec/constants.ts'
import { drained, type ExecuteNodeFn, pump } from './jobs.ts'
import { carried, isUnwinding, type Unwinding } from './control.ts'
import { Channel, JobConsole } from '../../shell/console/index.ts'
import { concat } from '../../io/cachable_iterator.ts'

type Result = [ByteSource | null, IOResult, ExecutionNode]

const TO_STDOUT = Symbol('stdout')
const TO_STDERR = Symbol('stderr')
// Where `>&-` points a descriptor: bytes written there are dropped, and a
// command whose stdout was closed reports the write failure the way GNU
// echo does.
const CLOSED = Symbol('closed')
type FdDest = typeof TO_STDOUT | typeof TO_STDERR | typeof CLOSED | FileDescription

/** Ordered descriptor bindings for one command, restored after execution.
 * Output opens remain deferred until admission completes so a refused command
 * cannot truncate its targets; ordinary opens can still fail after execution. */
const UNREADABLE: unique symbol = Symbol('unreadable')
type Input = ByteSource | null | typeof UNREADABLE

export async function handleRedirect(
  executeNode: ExecuteNodeFn,
  dispatch: DispatchFn,
  command: TSNodeLike | null,
  redirects: readonly Redirect[],
  session: SessionState,
  stdin: ByteSource | null = null,
  callStack: CallStack | null = null,
  captureInput = false,
  sink?: JobConsole,
): Promise<Result> {
  const badFd = unsupportedDescriptor(redirects)
  if (badFd !== null) return shellFailure(badDescriptorLine(badFd))
  const inputs = new Map<number, Input>([
    [0, share(stdin)],
    [1, UNREADABLE],
    [2, UNREADABLE],
  ])
  const outputs = new Map<number, FdDest>([
    [0, CLOSED],
    [1, TO_STDOUT],
    [2, TO_STDERR],
  ])
  const inputDest = stdinDest(session)
  if (typeof inputDest === 'string') {
    const file = new FileDescription(ensureScope(inputDest), true)
    file.opened = true
    outputs.set(0, file)
  } else outputs.set(0, inputDest)
  const boundInput = session.descriptors.get(0)?.file
  if (boundInput != null) outputs.set(0, boundInput)
  if (stdin instanceof FileInput) outputs.set(0, stdin.description)
  if (session.execStdin instanceof FileInput) outputs.set(0, session.execStdin.description)
  for (const [fd, binding, source] of [
    [1, session.execStdout, session.execStdoutInput],
    [2, session.execStderr, session.execStderrInput],
  ] as const) {
    if (binding?.startsWith(OPEN_FOR_READING)) inputs.set(fd, source)
    else if (binding === EXEC_TO_STDIN) inputs.set(fd, inputs.get(0) ?? null)
  }
  const closed = persistentlyClosed(session)
  for (const [fd, descriptor] of session.descriptors) {
    if (fd <= 2) continue
    inputs.set(fd, descriptor.source ?? UNREADABLE)
    outputs.set(fd, descriptorOutput(descriptor))
    if (descriptor.identity === EXEC_CLOSED) closed.add(fd)
  }
  const files: FileDescription[] = []
  for (const r of redirects) {
    if (r.kind === RedirectKind.AMBIGUOUS) {
      const word = r.target instanceof PathSpec ? r.target.rawPath : String(r.target)
      return shellFailure(encodeText(`${word}: ambiguous redirect\n`))
    }
    if (typeof r.target === 'number') {
      if (r.target === FD_CLOSE) {
        closed.add(r.fd)
        inputs.set(r.fd, UNREADABLE)
        outputs.set(r.fd, CLOSED)
      } else if (r.target !== r.fd) {
        if (closed.has(r.target) || !outputs.has(r.target))
          return shellFailure(badDescriptorLine(r.target))
        let source = inputs.get(r.target) ?? null
        if (source !== UNREADABLE) {
          source = share(source ?? new Uint8Array())
          inputs.set(r.target, source)
        }
        inputs.set(r.fd, source)
        outputs.set(r.fd, outputs.get(r.target) ?? CLOSED)
        closed.delete(r.fd)
      }
      continue
    }
    const fds = r.fd === FD_BOTH ? [1, 2] : [r.fd]
    for (const fd of fds) {
      closed.delete(fd)
      inputs.set(fd, UNREADABLE)
      outputs.set(fd, CLOSED)
    }
    if (r.kind === RedirectKind.HEREDOC || r.kind === RedirectKind.HERESTRING) {
      const data = r.target
      if (typeof data === 'string') {
        let text = data
        if (r.kind === RedirectKind.HERESTRING) {
          if (text.length >= 2 && text.at(0) === text.at(-1) && ['"', "'"].includes(text.charAt(0)))
            text = text.slice(1, -1)
          text += '\n'
        }
        inputs.set(r.fd, r.fd === 0 ? encodeText(text) : new SharedInput(encodeText(text)))
      } else inputs.set(r.fd, data as ByteSource)
      continue
    }
    const scope = ensureScope(r.target)
    if (r.kind === RedirectKind.STDIN || r.kind === RedirectKind.READWRITE) {
      let source: ByteSource | null
      try {
        if (scope.virtual === '/dev/stdin' && r.kind === RedirectKind.STDIN) {
          inputs.set(r.fd, stdin)
          continue
        }
        source = (await dispatch('read', scope))[0] as ByteSource | null
      } catch (error) {
        if (r.kind === RedirectKind.READWRITE && isMissingPath(error)) source = new Uint8Array()
        else {
          if (!isFsError(error)) throw error
          return redirectFailure(scope, error)
        }
      }
      const data = await materialize(source)
      if (r.kind === RedirectKind.READWRITE) {
        const file = new FileDescription(scope, true)
        file.source = new FileInput(file, data)
        files.push(file)
        inputs.set(r.fd, file.source)
        outputs.set(r.fd, file)
      } else
        inputs.set(
          r.fd,
          data.byteLength === 0 && (await isDevice(dispatch, scope))
            ? new DeviceInput()
            : r.fd === 0
              ? data
              : new SharedInput(data),
        )
    } else {
      const file = new FileDescription(scope, r.append)
      files.push(file)
      for (const fd of fds) outputs.set(fd, file)
    }
  }
  const refusal = await openRefusal(dispatch, session, redirects)
  if (refusal !== null) return refusal
  const recorder = new JobConsole()
  for (const file of files) {
    if (file.source !== null) continue
    for (const [fd, channel] of [
      [1, Channel.STDOUT],
      [2, Channel.STDERR],
    ] as const) {
      if (outputs.get(fd) === file) {
        file.emit = (data) => recorder.emit(channel, data)
        break
      }
    }
  }
  let unwound: Unwinding | null = null
  let refused = false
  let io = new IOResult()
  const saved = session.descriptors
  const claimed = new Set(redirects.flatMap((r) => (r.fd === FD_BOTH ? [1, 2] : [r.fd])))
  session.descriptors = new Map([
    ...saved,
    ...[...outputs]
      .filter(([fd]) => fd > 2 || claimed.has(fd))
      .map(([fd, output]) => [fd, describe(output, inputs.get(fd) ?? null)] as const),
  ])
  const targets = redirects
    .filter(
      (r) =>
        typeof r.target !== 'number' &&
        r.kind !== RedirectKind.HEREDOC &&
        r.kind !== RedirectKind.HERESTRING,
    )
    .map((r) => ensureScope(r.target))
  const terminalOutput = session.terminalOutput
  session.terminalOutput = terminalOutput && outputs.get(1) === TO_STDOUT
  try {
    const given = inputs.get(0) ?? null
    if (command === null) {
      if (captureInput && given !== UNREADABLE) await pump(recorder, Channel.STDOUT, given)
    } else {
      const [, execIo, execNode] = await drained(
        recorder,
        ...(await runWithRedirectPaths(command, targets, () =>
          executeNode(
            command,
            session,
            given === UNREADABLE ? unreadableStdin() : given,
            callStack,
            { sink: recorder },
          ),
        )),
      )
      io = execIo
      refused = execNode.refused
    }
  } catch (error) {
    if (!isUnwinding(error)) throw error
    unwound = error
  } finally {
    for (const file of files) file.emit = null
    session.terminalOutput = terminalOutput
    for (const fd of claimed) {
      const original = saved.get(fd)
      if (original !== undefined) session.descriptors.set(fd, original)
      else session.descriptors.delete(fd)
    }
  }
  const [recorded] = await recorder.readFrom(0)
  const chunks: [Channel, Uint8Array][] = recorded.map((c) => [c.channel, c.data])
  if (refused) {
    outputs.clear()
    outputs.set(0, CLOSED)
    outputs.set(1, TO_STDOUT)
    outputs.set(2, TO_STDERR)
    for (const r of redirects)
      if (typeof r.target === 'number') outputs.set(r.fd, outputs.get(r.target) ?? CLOSED)
  }
  if (
    outputs.get(1) === CLOSED &&
    command !== null &&
    chunks.some(([channel]) => channel === Channel.STDOUT)
  ) {
    chunks.push([Channel.STDERR, closedWriteLine(command)])
    io.exitCode = 1
  }
  const routed: [Channel, Uint8Array][] = []
  const writeFiles = async () => {
    const consumed = new Set<FileDescription>()
    let failedScope: PathSpec | null = null
    try {
      if (!refused)
        for (const file of files) {
          failedScope = file.scope
          const unique =
            files.filter((other) => other.scope.virtual === file.scope.virtual).length === 1
          const data = unique
            ? concat(
                chunks
                  .filter(([channel]) => outputs.get(channel === Channel.STDOUT ? 1 : 2) === file)
                  .map(([, data]) => data),
              )
            : new Uint8Array()
          await writeDescription(dispatch, session, file, data)
          if (unique) {
            consumed.add(file)
            if (data.byteLength > 0) io.writes[file.scope.virtual] = data
          }
        }
      for (const [channel, data] of chunks) {
        const dest = outputs.get(channel === Channel.STDOUT ? 1 : 2)
        if (dest === TO_STDOUT) routed.push([Channel.STDOUT, data])
        else if (dest === TO_STDERR) routed.push([Channel.STDERR, data])
        else if (dest instanceof FileDescription && !consumed.has(dest)) {
          failedScope = dest.scope
          await writeDescription(dispatch, session, dest, data)
          io.writes[dest.scope.virtual] = data
        }
      }
    } catch (error) {
      if (!isFsError(error) || failedScope === null) throw error
      routed.push([Channel.STDERR, redirectErrorLine(failedScope, error)])
      io.exitCode = 1
    }
  }
  if (command === null) await writeFiles()
  else await runWithRedirectPaths(command, targets, writeFiles)
  let stdout: Uint8Array | null = null
  io.stderr = null
  if (sink !== undefined) for (const [channel, data] of routed) await sink.emit(channel, data)
  else {
    const joined = (channel: Channel): Uint8Array | null => {
      const data = concat(routed.filter(([c]) => c === channel).map(([, d]) => d))
      return data.byteLength === 0 ? null : data
    }
    stdout = joined(Channel.STDOUT)
    io.stderr = joined(Channel.STDERR)
  }
  if (unwound !== null) throw await carried(unwound, stdout, new IOResult({ stderr: io.stderr }))
  return [stdout, io, new ExecutionNode({ command: 'redirect', exitCode: io.exitCode, refused })]
}

function descriptorOutput(descriptor: Descriptor): FdDest {
  if (descriptor.file !== null) return descriptor.file
  if (descriptor.identity === EXEC_TO_STDOUT) return TO_STDOUT
  if (descriptor.identity === EXEC_TO_STDERR) return TO_STDERR
  if (descriptor.identity.startsWith('/')) {
    const file = new FileDescription(ensureScope(descriptor.identity), true)
    file.opened = true
    return file
  }
  return CLOSED
}

function describe(output: FdDest, source: Input): Descriptor {
  const input = source instanceof SharedInput ? source : null
  if (output instanceof FileDescription)
    return {
      identity: (source instanceof FileInput ? '<>' : '') + output.scope.virtual,
      append: output.append,
      source: input,
      file: output,
    }
  const identity =
    output === TO_STDOUT
      ? EXEC_TO_STDOUT
      : output === TO_STDERR
        ? EXEC_TO_STDERR
        : input !== null
          ? OPEN_FOR_READING
          : EXEC_CLOSED
  return { identity, append: false, source: input, file: null }
}

/**
 * GNU stderr line for a redirect target that could not be opened.
 *
 * GNU bash 5.2.37 answers both `cat < missing` and `echo x > /nosuchdir/f`
 * with `bash: line 1: <target>: No such file or directory` and exit 1: the
 * error belongs to the shell, not the command, and the rest of the line keeps
 * running (`;` continues, `&&` short-circuits, `||` runs).
 *
 * Deliberate divergence from bash: the `bash: line N:` prefix is dropped, so
 * the line is `<target>: <strerror>`. This matches the house style already
 * set by the other shell-attributed error, `nosuchcmd: command not found`
 * (bash prints `bash: line 1: nosuchcmd: command not found`) — `bash:` is
 * bash's `$0` and mirage is not bash, and `line N` has no meaning for a
 * one-line `Workspace.shell` call.
 *
 * The label is the target's own spelling, never the error's message: backends
 * raise write failures with prose in the message (`parent directory does not
 * exist: /nodir`), which used to reach the user as the path.
 */
function redirectErrorLine(scope: PathSpec, err: unknown): Uint8Array {
  const strerror = fsStrerror(err)
  const label = scope.rawPath
  return new TextEncoder().encode(strerror !== null ? `${label}: ${strerror}\n` : `${label}\n`)
}

/** GNU's line for a write onto a closed stdout, in the command's name. */
function closedWriteLine(command: TSNodeLike): Uint8Array {
  const words = getText(command)
    .split(/\s+/)
    .filter((w) => w !== '')
  const name = words[0] ?? 'redirect'
  return new TextEncoder().encode(`${name}: write error: Bad file descriptor\n`)
}

/** Shell-attributed IOResult for a redirect target that cannot be opened. */
function redirectFailure(scope: PathSpec, err: unknown): Result {
  return shellFailure(redirectErrorLine(scope, err))
}

/**
 * Shell-attributed IOResult that replaces the command's whole run.
 *
 * bash never runs the command and stops processing redirects at the first
 * failure, so this replaces the whole result. Returning an IOResult rather
 * than rethrowing is what keeps the rest of the line alive.
 */
function shellFailure(line: Uint8Array): Result {
  const io = new IOResult({ exitCode: 1, stderr: line })
  return [null, io, new ExecutionNode({ command: 'redirect', exitCode: 1 })]
}

/** Whether a redirect target is a character device (`/dev/null`). */
async function isDevice(dispatch: DispatchFn, scope: PathSpec): Promise<boolean> {
  let stat: unknown
  try {
    ;[stat] = await dispatch('stat', scope)
  } catch (err) {
    if (!isFsError(err)) throw err
    return false
  }
  return stat instanceof FileStat && stat.type === FileType.CHAR_DEVICE
}

/**
 * Refuse the whole statement when one of its opens cannot happen.
 *
 * Returned *instead of* running the command, because that is what bash
 * does: it opens every redirect before it forks, so a refusal means the
 * command never runs. `set -C; touch marker > existing` leaves no marker
 * behind. Deciding this after the fact only matched the file contents,
 * and on `rm f > f` it did not even do that — the command deleted its
 * own target first, so the probe found nothing there and let the line
 * succeed.
 *
 * Two opens refuse. A target typed with a trailing slash is one whatever
 * is there: open(2) with O_CREAT answers `missing/` and `reg/` alike with
 * EISDIR before looking anything up, so bash prints `missing/: Is a
 * directory` and creates nothing, where writing the normalized name would
 * have left a regular file called `missing`. That test is on the spelling
 * alone and costs no round trip, which is a deliberate divergence for a
 * slashed target under a parent that is itself absent: bash reports the
 * parent first (ENOENT), this reads `Is a directory` too. The other is
 * `set -C`, described next.
 *
 * `set -C` refuses a truncating open onto anything that already exists —
 * an empty file counts, since the test is existence and not size — while
 * `>>` is always allowed and `>|` overrides for that one redirect without
 * clearing the option. A directory reached under the option is refused
 * too, in GNU's own wording for that case rather than the noclobber one.
 * bash stops at the first target it cannot open, so the scan reports one
 * line and stops.
 *
 * The opens are modelled in the order they were written, because each one
 * is visible to the next: `set -C; echo x > a > a` creates `a` on the
 * first redirect and then refuses the second, even though `a` did not
 * exist when the statement began. Probing every target against one
 * pre-command snapshot passed both and wrote the output. `>>` and `>|`
 * never refuse but do create, so they count as opens too.
 *
 * The stat is skipped unless the option is on, so the ordinary redirect
 * path costs no extra round trip. A directory typed without a slash needs
 * none here: the open itself answers `Is a directory`, from the kernel on
 * a real filesystem and from the store's own directory table on a keyed
 * one, and the write path renders it.
 *
 * Targets are stat'd through the op dispatcher rather than a backend, so
 * a redirect that lands on another mount is answered by the mount that
 * owns it.
 */
async function openRefusal(
  dispatch: DispatchFn,
  session: SessionState,
  redirects: readonly Redirect[],
): Promise<Result | null> {
  const noclobber = session.shellOptions.noclobber === true
  const opened = new Set<string>()
  const pending: PathSpec[] = []
  for (const r of redirects) {
    if (
      r.kind === RedirectKind.STDIN ||
      r.kind === RedirectKind.READWRITE ||
      r.kind === RedirectKind.HEREDOC ||
      r.kind === RedirectKind.HERESTRING ||
      typeof r.target === 'number'
    ) {
      continue
    }
    const scope = ensureScope(r.target)
    if (scope.rawPath.endsWith('/')) {
      const earlier = await applyPendingOpens(dispatch, pending)
      if (earlier !== null) return earlier
      return shellFailure(new TextEncoder().encode(`${scope.rawPath}: Is a directory\n`))
    }
    const path = scope.virtual
    let exists = opened.has(path)
    let isDir = false
    if (noclobber && !exists) {
      let stat: unknown
      try {
        ;[stat] = await dispatch('stat', scope)
      } catch (err) {
        // No target to overwrite is the ordinary case the option allows;
        // anything that is not a filesystem error is a bug and propagates.
        if (!isFsError(err)) throw err
        stat = null
      }
      exists = stat instanceof FileStat
      isDir = stat instanceof FileStat && stat.type === FileType.DIRECTORY
    }
    if (noclobber && exists && !r.append && !r.clobber) {
      const earlier = await applyPendingOpens(dispatch, pending)
      if (earlier !== null) return earlier
      const detail = isDir ? 'Is a directory' : 'cannot overwrite existing file'
      const err = new TextEncoder().encode(`${scope.rawPath}: ${detail}\n`)
      const io = new IOResult({ exitCode: 1, stderr: err })
      return [null, io, new ExecutionNode({ command: 'redirect', exitCode: 1 })]
    }
    // This open succeeds, so the target exists for every redirect after
    // it, and a truncating one leaves it empty to be found. Without the
    // option nothing was stat'd, so an append target of unknown standing
    // is not listed: pre-opening it with an empty write would truncate a
    // file that is there.
    opened.add(path)
    if (!r.append || (noclobber && !exists)) pending.push(scope)
  }
  return null
}

/**
 * Apply the opens a refused statement already performed.
 *
 * bash opens redirects left to right, so the ones before the refused one
 * have happened by the time it refuses: `set -C; echo x >> a > a` leaves
 * `a` existing and empty, and `>| a > a` truncates it. Only targets the
 * scan found absent, or opened for truncation, are listed, so an append
 * onto an existing file keeps its bytes.
 *
 * An earlier open that fails is the statement's refusal instead: bash stops
 * at the first open it cannot perform, so `echo x > /nodir/f > reg/` reports
 * `/nodir/f: No such file or directory` and never reaches the slashed target,
 * and the opens after the failed one are not performed either. Returns that
 * failure, or null when every open went through.
 */
async function applyPendingOpens(
  dispatch: DispatchFn,
  pending: PathSpec[],
): Promise<Result | null> {
  for (const scope of pending) {
    try {
      await dispatch('write', scope, [new Uint8Array()])
    } catch (err) {
      if (!isFsError(err)) throw err
      return redirectFailure(scope, err)
    }
  }
  return null
}

/** The descriptors an `exec` closed for the shell, which a line's dup
 * from refuses before the command runs. */
function persistentlyClosed(session: SessionState): Set<number> {
  const closed = new Set<number>()
  if (session.execStdinIdentity === EXEC_CLOSED) closed.add(FD_STDIN)
  if (session.execStdout === EXEC_CLOSED) closed.add(FD_STDOUT)
  if (session.execStderr === EXEC_CLOSED) closed.add(FD_STDERR)
  return closed
}

/**
 * Where a write through fd 0 lands, read off the shell's bindings. Its
 * own read end, a closed descriptor and a file's read end take no write
 * (`echo x >&0` is bash's `write error: Bad file descriptor` with stdin a
 * pipe); a terminal stream dup'd onto it (`exec 0<&1`) writes where that
 * stream goes; a file opened for writing (`exec 0>f`) is the file.
 */
function stdinDest(session: SessionState): FdDest | string {
  const id = session.execStdinIdentity
  if (id === null || id === EXEC_CLOSED || id.startsWith(OPEN_FOR_READING)) return CLOSED
  if (id === EXEC_TO_STDOUT) return TO_STDOUT
  if (id === EXEC_TO_STDERR) return TO_STDERR
  return id
}

function ensureScope(target: unknown): PathSpec {
  if (target instanceof PathSpec) return target
  if (typeof target === 'string') return toScope(target)
  return toScope(String(target))
}

function toScope(path: string): PathSpec {
  const lastSlash = path.lastIndexOf('/')
  const directory = lastSlash >= 0 ? path.slice(0, lastSlash + 1) : '/'
  return new PathSpec({ vfsPath: stripSlash(path), virtual: path, directory, resolved: true })
}
