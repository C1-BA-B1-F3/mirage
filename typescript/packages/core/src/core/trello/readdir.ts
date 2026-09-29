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

import type { TrelloAccessor } from '../../accessor/trello.ts'
import { IndexEntry } from '../../cache/index/config.ts'
import { makeReaddir } from '../hierarchy/readdir.ts'
import type { ScopeMatch } from '../hierarchy/scope.ts'
import {
  getBoard,
  listBoardLabels,
  listBoardLists,
  listBoardMembers,
  listListCards,
  listWorkspaceBoards,
  listWorkspaces,
} from './client.ts'
import {
  normalizeBoard,
  normalizeCard,
  normalizeLabel,
  normalizeList,
  normalizeMember,
  normalizeWorkspace,
  toJsonBytes,
} from './normalize.ts'
import {
  boardDirname,
  cardDirname,
  labelFilename,
  listDirname,
  memberFilename,
  workspaceDirname,
} from './pathing.ts'
import { detectScope } from './scope.ts'

function pickString(record: Record<string, unknown>, key: string): string {
  const value = record[key]
  return typeof value === 'string' ? value : ''
}

function extraSize(entry: IndexEntry): number | null {
  const value = entry.extra.json_size
  return typeof value === 'number' ? value : null
}

/** The workspaces the mount shows: the member's, narrowed to `workspaceId` when it is set. */
export async function filteredWorkspaces(
  accessor: TrelloAccessor,
): Promise<Record<string, unknown>[]> {
  let workspaces = await listWorkspaces(accessor.transport)
  if (accessor.workspaceId !== null && accessor.workspaceId !== '') {
    workspaces = workspaces.filter((w) => pickString(w, 'id') === accessor.workspaceId)
  }
  return workspaces
}

/** A workspace's open boards the mount shows, narrowed to `boardIds` when it is set. */
export async function filteredBoards(
  accessor: TrelloAccessor,
  workspaceId: string,
): Promise<Record<string, unknown>[]> {
  let boards = await listWorkspaceBoards(accessor.transport, workspaceId)
  if (accessor.boardIds !== null && accessor.boardIds.length > 0) {
    const allowed = new Set(accessor.boardIds)
    boards = boards.filter((b) => allowed.has(pickString(b, 'id')))
  }
  return boards
}

/** Whether `workspaceId` or `boardIds` narrows the mount. */
export function scopeIsNarrowed(accessor: TrelloAccessor): boolean {
  const byWorkspace = accessor.workspaceId !== null && accessor.workspaceId !== ''
  const byBoard = accessor.boardIds !== null && accessor.boardIds.length > 0
  return byWorkspace || byBoard
}

/**
 * Whether the mount's scope admits a board addressed by id.
 *
 * The two knobs that narrow the listing narrow an id too: a board
 * `boardIds` leaves out, or one outside `workspaceId`, is not this
 * mount's to read or write. Unnarrowed, every id is admitted without a
 * call; `workspaceId` costs one board fetch. Mirrors python's
 * `board_in_scope`.
 */
export async function boardInScope(accessor: TrelloAccessor, boardId: string): Promise<boolean> {
  if (!scopeIsNarrowed(accessor)) return true
  if (boardId === '') return false
  if (accessor.boardIds !== null && accessor.boardIds.length > 0) {
    if (!accessor.boardIds.includes(boardId)) return false
  }
  if (accessor.workspaceId === null || accessor.workspaceId === '') return true
  const board = await getBoard(accessor.transport, boardId)
  return pickString(board, 'idOrganization') === accessor.workspaceId
}

async function listWorkspacesDir(
  accessor: TrelloAccessor,
  _match: ScopeMatch,
): Promise<[string, IndexEntry][]> {
  const entries: [string, IndexEntry][] = []
  for (const workspace of await filteredWorkspaces(accessor)) {
    const dirname = workspaceDirname(workspace)
    // workspace.json renders the workspace object this listing already
    // fetched, so its exact size rides the directory entry for the child
    // listing to read back without another call.
    entries.push([
      dirname,
      new IndexEntry({
        id: pickString(workspace, 'id'),
        name:
          pickString(workspace, 'displayName') ||
          pickString(workspace, 'name') ||
          pickString(workspace, 'id'),
        resourceType: 'trello/workspace',
        remoteTime: '',
        vfsName: dirname,
        extra: { json_size: toJsonBytes(normalizeWorkspace(workspace)).byteLength },
      }),
    ])
  }
  return entries
}

function listWorkspace(
  _accessor: TrelloAccessor,
  _match: ScopeMatch,
  entry: IndexEntry,
): Promise<[string, IndexEntry][]> {
  return Promise.resolve<[string, IndexEntry][]>([
    [
      'workspace.json',
      new IndexEntry({
        id: entry.id,
        name: 'workspace.json',
        resourceType: 'trello/workspace_json',
        vfsName: 'workspace.json',
        size: extraSize(entry),
      }),
    ],
    [
      'boards',
      new IndexEntry({
        id: entry.id,
        name: 'boards',
        resourceType: 'trello/boards_dir',
        vfsName: 'boards',
      }),
    ],
  ])
}

async function listBoards(
  accessor: TrelloAccessor,
  match: ScopeMatch,
  _entry: IndexEntry,
): Promise<[string, IndexEntry][]> {
  const entries: [string, IndexEntry][] = []
  for (const board of await filteredBoards(accessor, match.slots.workspace_id ?? '')) {
    const dirname = boardDirname(board)
    // board.json's normalizer only uses fields the board listing already
    // carries, so its exact size is free here.
    entries.push([
      dirname,
      new IndexEntry({
        id: pickString(board, 'id'),
        name: pickString(board, 'name') || pickString(board, 'id'),
        resourceType: 'trello/board',
        remoteTime: pickString(board, 'dateLastActivity'),
        vfsName: dirname,
        extra: { json_size: toJsonBytes(normalizeBoard(board)).byteLength },
      }),
    ])
  }
  return entries
}

function listBoard(
  _accessor: TrelloAccessor,
  _match: ScopeMatch,
  entry: IndexEntry,
): Promise<[string, IndexEntry][]> {
  return Promise.resolve<[string, IndexEntry][]>([
    [
      'board.json',
      new IndexEntry({
        id: entry.id,
        name: 'board.json',
        resourceType: 'trello/board_json',
        vfsName: 'board.json',
        size: extraSize(entry),
        remoteTime: entry.remoteTime,
      }),
    ],
    [
      'members',
      new IndexEntry({
        id: entry.id,
        name: 'members',
        resourceType: 'trello/members_dir',
        vfsName: 'members',
      }),
    ],
    [
      'labels',
      new IndexEntry({
        id: entry.id,
        name: 'labels',
        resourceType: 'trello/labels_dir',
        vfsName: 'labels',
      }),
    ],
    [
      'lists',
      new IndexEntry({
        id: entry.id,
        name: 'lists',
        resourceType: 'trello/lists_dir',
        vfsName: 'lists',
      }),
    ],
  ])
}

async function listMembers(
  accessor: TrelloAccessor,
  match: ScopeMatch,
  _entry: IndexEntry,
): Promise<[string, IndexEntry][]> {
  const members = await listBoardMembers(accessor.transport, match.slots.board_id ?? '')
  return members.map((member): [string, IndexEntry] => {
    const filename = memberFilename(member)
    return [
      filename,
      new IndexEntry({
        id: pickString(member, 'id'),
        name:
          pickString(member, 'fullName') ||
          pickString(member, 'username') ||
          pickString(member, 'id'),
        resourceType: 'trello/member',
        remoteTime: '',
        vfsName: filename,
        size: toJsonBytes(normalizeMember(member)).byteLength,
      }),
    ]
  })
}

async function listLabels(
  accessor: TrelloAccessor,
  match: ScopeMatch,
  _entry: IndexEntry,
): Promise<[string, IndexEntry][]> {
  const labels = await listBoardLabels(accessor.transport, match.slots.board_id ?? '')
  return labels.map((label): [string, IndexEntry] => {
    const filename = labelFilename(label)
    return [
      filename,
      new IndexEntry({
        id: pickString(label, 'id'),
        name: pickString(label, 'name') || pickString(label, 'color') || pickString(label, 'id'),
        resourceType: 'trello/label',
        remoteTime: '',
        vfsName: filename,
        size: toJsonBytes(normalizeLabel(label)).byteLength,
      }),
    ]
  })
}

async function listLists(
  accessor: TrelloAccessor,
  match: ScopeMatch,
  _entry: IndexEntry,
): Promise<[string, IndexEntry][]> {
  const lists = await listBoardLists(accessor.transport, match.slots.board_id ?? '')
  return lists.map((lst): [string, IndexEntry] => {
    const dirname = listDirname(lst)
    // list.json's normalizer only uses fields the list listing already
    // carries, so its exact size is free here.
    return [
      dirname,
      new IndexEntry({
        id: pickString(lst, 'id'),
        name: pickString(lst, 'name') || pickString(lst, 'id'),
        resourceType: 'trello/list',
        remoteTime: '',
        vfsName: dirname,
        extra: { json_size: toJsonBytes(normalizeList(lst)).byteLength },
      }),
    ]
  })
}

function listList(
  _accessor: TrelloAccessor,
  _match: ScopeMatch,
  entry: IndexEntry,
): Promise<[string, IndexEntry][]> {
  return Promise.resolve<[string, IndexEntry][]>([
    [
      'list.json',
      new IndexEntry({
        id: entry.id,
        name: 'list.json',
        resourceType: 'trello/list_json',
        vfsName: 'list.json',
        size: extraSize(entry),
      }),
    ],
    [
      'cards',
      new IndexEntry({
        id: entry.id,
        name: 'cards',
        resourceType: 'trello/cards_dir',
        vfsName: 'cards',
      }),
    ],
  ])
}

async function listCards(
  accessor: TrelloAccessor,
  match: ScopeMatch,
  _entry: IndexEntry,
): Promise<[string, IndexEntry][]> {
  const cards = await listListCards(accessor.transport, match.slots.list_id ?? '')
  return cards.map((card): [string, IndexEntry] => {
    const dirname = cardDirname(card)
    // card.json's normalizer only uses fields the card listing already
    // carries, so its exact size is free here.
    return [
      dirname,
      new IndexEntry({
        id: pickString(card, 'id'),
        name: pickString(card, 'name') || pickString(card, 'id'),
        resourceType: 'trello/card',
        remoteTime: pickString(card, 'dateLastActivity'),
        vfsName: dirname,
        extra: { json_size: toJsonBytes(normalizeCard(card)).byteLength },
      }),
    ]
  })
}

function listCard(
  _accessor: TrelloAccessor,
  _match: ScopeMatch,
  entry: IndexEntry,
): Promise<[string, IndexEntry][]> {
  // comments.jsonl needs a per-card actions call and stays size-unknown.
  return Promise.resolve<[string, IndexEntry][]>([
    [
      'card.json',
      new IndexEntry({
        id: entry.id,
        name: 'card.json',
        resourceType: 'trello/card_json',
        vfsName: 'card.json',
        size: extraSize(entry),
        remoteTime: entry.remoteTime,
      }),
    ],
    [
      'comments.jsonl',
      new IndexEntry({
        id: entry.id,
        name: 'comments.jsonl',
        resourceType: 'trello/comments_jsonl',
        vfsName: 'comments.jsonl',
        remoteTime: entry.remoteTime,
      }),
    ],
  ])
}

export const readdir = makeReaddir<TrelloAccessor>(detectScope, {
  listers: {
    workspaces: listWorkspacesDir,
  },
  entryListers: {
    workspace: listWorkspace,
    boards: listBoards,
    board: listBoard,
    members: listMembers,
    labels: listLabels,
    lists: listLists,
    list: listList,
    cards: listCards,
    card: listCard,
  },
  staticRoot: ['workspaces'],
})
