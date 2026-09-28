import { concat } from '../../../io/cachable_iterator.ts'
import { IOResult, materialize, type ByteSource } from '../../../io/types.ts'
import type { PathSpec } from '../../../types.ts'
import { gunzipStream } from '../../../utils/compress.ts'
import {
  enoent,
  fsErrorLine,
  GzipDataError,
  isDotWalkError,
  isEisdir,
  isEnoent,
  isFsError,
} from '../../../utils/errors.ts'
import { mountedPath, respelled } from '../../../utils/key_prefix.ts'
import {
  GZIP_KNOWN_SUFFIXES,
  GZIP_MAX_SUFFIX,
  GZIP_RETRY_SUFFIXES,
  GZIP_SUFFIX,
  GZIP_TAR_SUFFIXES,
} from '../constants.ts'
import type { StatFn } from './archive/walk.ts'
import { pathExists } from '../utils/copy.ts'
import { STDIN_OPERAND } from '../utils/constants.ts'
import { stdinStream } from '../utils/stream.ts'

const ENC = new TextEncoder()

function asciiLower(text: string): string {
  return text.replace(/[A-Z]/g, (c) => c.toLowerCase())
}

/**
 * The compression suffix gzip reads off `name`, as spelled there.
 *
 * gzip 1.13's get_suffix: the -S suffix and the ones gzip always knows,
 * compared without regard to ASCII case, and only where the name is longer
 * than the suffix with no slash right before it, so neither `.gz` nor
 * `d/.gz` has one. A -S suffix that ends one of the built-in ones is tried
 * after them, or `-S z` would take the `z` off `a.gz`. Mirrors Python's
 * gzip_suffix.
 */
export function gzipSuffix(name: string, suffix: string): string | null {
  const inner = GZIP_KNOWN_SUFFIXES.some((k) => suffix.length < k.length && k.endsWith(suffix))
  const own = asciiLower(suffix)
  const order = inner ? [...GZIP_KNOWN_SUFFIXES, own] : [own, ...GZIP_KNOWN_SUFFIXES]
  const lowered = asciiLower(name)
  for (const known of order) {
    const cut = lowered.length - known.length
    if (cut > 0 && lowered.endsWith(known) && lowered[cut - 1] !== '/') return name.slice(cut)
  }
  return null
}

/** gzip's refusal of a -S suffix it cannot use, before any input. Mirrors
 * Python's suffix_refusal. */
export function suffixRefusal(suffix: string): IOResult | null {
  const bytes = ENC.encode(suffix).byteLength
  if (bytes > 0 && bytes <= GZIP_MAX_SUFFIX) return null
  return new IOResult({ exitCode: 1, stderr: ENC.encode(`gzip: invalid suffix '${suffix}'\n`) })
}

/**
 * The output `gzip -d` names for `path`, typed and mounted; null for a name
 * with no suffix gzip knows. `.tgz` and `.taz`, in any case, become `.tar`;
 * any other suffix is dropped.
 */
function decompressed(path: PathSpec, suffix: string): [string, PathSpec] | null {
  const found = gzipSuffix(path.rawPath, suffix)
  if (found === null) return null
  const tar = (GZIP_TAR_SUFFIXES as readonly string[]).includes(asciiLower(found)) ? '.tar' : ''
  const cut = found.length
  return [path.rawPath.slice(0, -cut) + tar, mountedPath(path, path.mountPath.slice(0, -cut) + tar)]
}

/**
 * The names gzip -d opens in turn when `path` does not exist.
 *
 * Each is the name as typed with one suffix appended, in the same directory;
 * the empty name makes the suffix itself the name. A name ending in a slash
 * or a dot, or one whose walk failed before its last component, has no
 * directory to hold a suffixed twin, so every one of them misses too. A
 * retried name is read on the operand's own mount, where a namespace link is
 * not followed.
 */
function retries(path: PathSpec, missing: unknown, suffix: string): PathSpec[] {
  const suffixes = suffix === GZIP_SUFFIX ? GZIP_RETRY_SUFFIXES : [suffix, ...GZIP_RETRY_SUFFIXES]
  const typed = path.rawPath
  if (typed === '') {
    const base = path.mountPath.replace(/\/+$/, '') + '/'
    return suffixes.map((s) => respelled(mountedPath(path, base + s), s))
  }
  const last = typed.slice(typed.lastIndexOf('/') + 1)
  if (last === '' || last === '.' || last === '..' || isDotWalkError(missing)) return []
  return suffixes.map((s) => respelled(mountedPath(path, path.mountPath + s), typed + s))
}

async function* resumed(
  first: IteratorResult<Uint8Array>,
  rest: AsyncIterator<Uint8Array>,
): AsyncIterable<Uint8Array> {
  if (first.done === true) return
  yield first.value
  for (;;) {
    const next = await rest.next()
    if (next.done === true) return
    yield next.value
  }
}

/** `source` read up to its first chunk, so a failed open throws here. */
async function opened(source: AsyncIterable<Uint8Array>): Promise<AsyncIterable<Uint8Array>> {
  const iterator = source[Symbol.asyncIterator]()
  return resumed(await iterator.next(), iterator)
}

interface DecompressOptions {
  stdin: ByteSource | null
  toStdout?: boolean
  testOnly?: boolean
  keep?: boolean
  force?: boolean
  quiet?: boolean
  suffix?: string
  write?: (path: PathSpec, data: Uint8Array) => Promise<void>
  unlink?: (path: PathSpec) => Promise<void>
  stat?: StatFn
}

/**
 * Decode operands in order the way gzip 1.13 does, in its voice.
 *
 * gunzip and zcat are gzip, so every line says `gzip:`. A missing name
 * without a suffix gzip knows is retried with each suffix and reported with
 * the -S one. In place, a name with no known suffix and an output already
 * there are skipped with a warning (exit 2), and so is a directory anywhere;
 * a warning under -q prints nothing and keeps its exit code, except the
 * unknown suffix, which -q drops whole. -f copies input that is not gzip when
 * the output is stdout. An input stdin cannot open as gzip ends the run, as
 * gzip exits there.
 *
 * With -f, an output already there is replaced, and when the input then
 * turns out corrupt GNU has already unlinked it: mirage keeps it. Mirrors
 * Python's decompress_inputs.
 */
export async function decompressInputs(
  paths: PathSpec[],
  read: (path: PathSpec) => AsyncIterable<Uint8Array>,
  options: DecompressOptions,
): Promise<[ByteSource | null, IOResult]> {
  const suffix = options.suffix ?? GZIP_SUFFIX
  const refused = suffixRefusal(suffix)
  if (refused !== null) return [null, refused]
  const force = options.force === true
  const quiet = options.quiet === true
  const testOnly = options.testOnly === true
  const operands = paths.length > 0 ? paths : [STDIN_OPERAND]
  const stream = stdinStream(read, options.stdin)
  const io = new IOResult()
  let errors = ''
  function report(line: string, code: number, warning = false): void {
    if (!(warning && quiet)) {
      errors += line
      io.stderr = ENC.encode(errors)
    }
    if (io.exitCode !== 1) io.exitCode = code
  }
  function fail(err: GzipDataError, shown: string): void {
    report(err.render(shown), err.exitCode, err.exitCode === 2)
  }
  async function openOne(
    path: PathSpec,
    source: (p: PathSpec) => AsyncIterable<Uint8Array>,
  ): Promise<[PathSpec, AsyncIterable<Uint8Array>] | null> {
    const retry = gzipSuffix(path.rawPath, suffix) === null
    const names = [path]
    for (const name of names) {
      try {
        return [name, await opened(source(name))]
      } catch (err) {
        if (isEisdir(err)) {
          report(`gzip: ${name.rawPath} is a directory -- ignored\n`, 2, true)
          return null
        }
        if (isEnoent(err)) {
          if (retry && name === path) names.push(...retries(path, err, suffix))
          continue
        }
        if (!isFsError(err)) throw err
        report(fsErrorLine('gzip', name, err), 1)
        return null
      }
    }
    const missing = retry ? path.rawPath + suffix : path.rawPath
    report(fsErrorLine('gzip', missing, enoent(missing)), 1)
    return null
  }
  async function* run(): AsyncIterable<Uint8Array> {
    for (const operand of operands) {
      const onStdin = operand.rawPath === '-'
      const inPlace = !(options.toStdout === true || testOnly || onStdin)
      let path = operand
      let source: AsyncIterable<Uint8Array>
      if (onStdin) source = stream(operand)
      else {
        const found = await openOne(operand, inPlace ? read : stream)
        if (found === null) continue
        ;[path, source] = found
      }
      const shown = onStdin ? 'stdin' : path.rawPath
      const output = inPlace ? decompressed(path, suffix) : null
      if (inPlace && output === null) {
        if (!quiet) report(`gzip: ${shown}: unknown suffix -- ignored\n`, 2)
        continue
      }
      const chunks: Uint8Array[] = []
      let failure: GzipDataError | null = null
      try {
        for await (const chunk of gunzipStream(source, testOnly, force && !inPlace)) {
          if (inPlace) chunks.push(chunk)
          else if (!testOnly) yield chunk
        }
      } catch (err) {
        if (err instanceof GzipDataError) failure = err
        else {
          if (!isFsError(err)) throw err
          report('\n' + fsErrorLine('gzip', shown, err), 1)
          return
        }
      }
      if (output === null) {
        if (failure !== null) {
          fail(failure, shown)
          if (failure.fatal || (onStdin && failure.firstHeader)) return
        }
        continue
      }
      if (failure?.firstHeader === true) {
        fail(failure, shown)
        if (failure.fatal) return
        continue
      }
      if (options.write === undefined || options.unlink === undefined)
        throw new Error('in-place decompression requires write and unlink')
      const [outName, out] = output
      const existed = options.stat !== undefined && (await pathExists(options.stat, out))
      if (existed && !force) {
        report(`gzip: ${outName} already exists;\tnot overwritten\n`, 2)
        continue
      }
      if (failure !== null) {
        fail(failure, shown)
        if (failure.fatal) return
        if (!failure.keepsOutput) continue
      }
      const data = concat(chunks)
      try {
        await options.write(out, data)
      } catch (err) {
        if (!isFsError(err)) throw err
        const line = fsErrorLine('gzip', outName, err)
        report(existed ? line : '\n' + line, 1)
        if (existed) continue
        return
      }
      io.writes[out.mountPath] = data
      if (options.keep !== true) await options.unlink(path)
    }
  }
  const body = run()
  if (testOnly || operands.some((p) => !(options.toStdout === true || p.rawPath === '-'))) {
    const output = await materialize(body)
    return [output.byteLength > 0 ? output : null, io]
  }
  return [body, io]
}
