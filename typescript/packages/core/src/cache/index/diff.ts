import type { Evicted } from './config.ts'
import { rstripSlash } from '../../utils/slash.ts'
import { compareCodePoints } from '../../utils/sort.ts'

/** Return topmost relative paths absent from a replacement tree, under a mount prefix. */
export function departed<T>(
  previous: Iterable<readonly [string, T]>,
  current: Iterable<string>,
  prefix: string,
  isFolder: (entry: T) => boolean,
): Evicted[] {
  const present = new Set(current)
  const gone = [...previous]
    .filter(([path]) => !present.has(path))
    .sort(([a], [b]) => compareCodePoints(a, b))
  const top: string[] = []
  const result: Evicted[] = []
  const stem = rstripSlash(prefix)
  for (const [path, entry] of gone) {
    if (!top.some((kept) => path.startsWith(`${kept}/`))) {
      top.push(path)
      result.push({ path: `${stem}/${path}`, folder: isFolder(entry) })
    }
  }
  return result
}
