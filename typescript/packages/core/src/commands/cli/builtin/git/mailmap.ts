import type { FlagView } from '../../../spec/flag_view.ts'
import { readOptional } from './io.ts'
import type { Dispatch, RepoLocation } from './types.ts'

export interface MailmapEntry {
  readonly email: string
  readonly name: string | null
  readonly mappedName: string | null
  readonly mappedEmail: string | null
}

export function parseMailmap(text: string): readonly MailmapEntry[] {
  const entries: MailmapEntry[] = []
  for (const line of text.split('\n')) {
    if (line.trimStart().startsWith('#')) continue
    const match = /^\s*([^<>]*?)\s*<([^<>]+)>(?:\s*([^<>]*?)\s*<([^<>]+)>)?/.exec(line)
    if (!match) continue
    const [, name = '', email = '', oldName, oldEmail] = match
    const originalName = oldName?.trim().toLowerCase() ?? ''
    entries.push({
      email: (oldEmail ?? email).toLowerCase(),
      name: originalName === '' ? null : originalName,
      mappedName: name.trim() || null,
      mappedEmail: oldEmail ? email : null,
    })
  }
  return entries
}

export function mappedIdentity(identity: string, entries: readonly MailmapEntry[]): string {
  const match = /(.*?)\s*<([^<>]*)>/.exec(identity)
  if (!match) return identity
  const [, name = '', email = ''] = match
  let chosenName = name,
    chosenEmail = email
  for (const specific of [false, true]) {
    for (const entry of entries) {
      if ((entry.name !== null) !== specific || entry.email !== email.toLowerCase()) continue
      if (entry.name !== null && entry.name !== name.toLowerCase()) continue
      chosenName = entry.mappedName ?? chosenName
      chosenEmail = entry.mappedEmail ?? chosenEmail
    }
  }
  return `${chosenName} <${chosenEmail}>`
}

export async function loadMailmap(
  dispatch: Dispatch,
  location: RepoLocation,
): Promise<readonly MailmapEntry[]> {
  const data = await readOptional(dispatch, `${location.worktree}/.mailmap`)
  return parseMailmap(new TextDecoder().decode(data ?? new Uint8Array()))
}

export function useMailmap(fl: FlagView, enabled: boolean): boolean {
  for (const [key] of fl.occurrences('mailmap', 'use_mailmap', 'no_mailmap', 'no_use_mailmap'))
    enabled = !key.startsWith('no_')
  return enabled
}
