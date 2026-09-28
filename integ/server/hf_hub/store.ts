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

import type { Minter } from '../kit/typescript/index.ts'
import { DEFAULT_REVISION, type C } from './config.ts'
import { gitOid, repoKey, type Blob, type Ref, type Repo } from './wire.ts'
import { rstripSlash } from '../kit/typescript/index.ts'

/**
 * A commit sha, minted rather than hashed.
 *
 * The real Hub's shas are git's, over a tree the fake does not build. What
 * every caller actually needs is that a sha is 40 hex characters, unique, and
 * stable across a read, so the counter is padded into that shape. Hashing the
 * content instead would make two identical commits share a sha, which git
 * avoids only because its commit object carries a timestamp and a parent.
 */
export function mintSha(minter: Minter): string {
  return String(minter.next('commit')).padStart(40, '0')
}

export async function repoOf(
  db: C,
  tenant: string,
  kind: string,
  namespace: string,
  name: string,
): Promise<Repo | null> {
  return db.hfRepo.findUnique({
    where: { tenant_kind_namespace_name: { tenant, kind, namespace, name } },
  })
}

export async function reposOfKind(db: C, tenant: string, kind: string): Promise<Repo[]> {
  return db.hfRepo.findMany({ where: { tenant, kind }, orderBy: { seq: 'asc' } })
}

export async function refsOf(db: C, tenant: string, repo: string): Promise<Ref[]> {
  return db.hfRef.findMany({ where: { tenant, repo }, orderBy: { name: 'asc' } })
}

/**
 * Resolve a revision to a commit sha.
 *
 * Three spellings resolve, in the Hub's own order: a branch name, a tag name,
 * and a bare sha. Null means the revision does not exist, which the caller
 * must report as RevisionNotFound rather than as an empty tree.
 */
export async function resolveRevision(
  db: C,
  tenant: string,
  repo: string,
  revision: string,
): Promise<string | null> {
  for (const refType of ['branch', 'tag']) {
    const ref = await db.hfRef.findUnique({
      where: { tenant_repo_refType_name: { tenant, repo, refType, name: revision } },
    })
    if (ref !== null) return ref.sha
  }
  const commit = await db.hfCommit.findUnique({
    where: { tenant_repo_sha: { tenant, repo, sha: revision } },
  })
  return commit === null ? null : commit.sha
}

export async function headSha(db: C, tenant: string, repo: string): Promise<string> {
  return (await resolveRevision(db, tenant, repo, DEFAULT_REVISION)) ?? ''
}

/**
 * When one commit was made. "" if the sha names no commit.
 *
 * A repository's modification time is this, never a blob's: `blobsAt` orders
 * by path and a commit carries every unchanged file forward with its old
 * timestamp, so the first blob is stale the moment a later commit touched
 * anything sorting after it, or only deleted something.
 */
export async function commitTime(
  db: C,
  tenant: string,
  repo: string,
  sha: string,
): Promise<string> {
  if (sha === '') return ''
  const commit = await db.hfCommit.findUnique({ where: { tenant_repo_sha: { tenant, repo, sha } } })
  return commit === null ? '' : commit.createdAt
}

export async function blobsAt(db: C, tenant: string, repo: string, sha: string): Promise<Blob[]> {
  return db.hfBlob.findMany({ where: { tenant, repo, sha }, orderBy: { path: 'asc' } })
}

export async function blobAt(
  db: C,
  tenant: string,
  repo: string,
  sha: string,
  path: string,
): Promise<Blob | null> {
  return db.hfBlob.findUnique({ where: { tenant_repo_sha_path: { tenant, repo, sha, path } } })
}

export async function createRepo(
  db: C,
  tenant: string,
  kind: string,
  namespace: string,
  name: string,
  options: { private?: boolean; sdk?: string | null; now: string },
  minter: Minter,
): Promise<Repo> {
  const repo = await db.hfRepo.create({
    data: {
      tenant,
      kind,
      namespace,
      name,
      private: options.private ?? false,
      sdk: options.sdk ?? null,
      createdAt: options.now,
      seq: minter.next('repo'),
    },
  })
  // A new repository is not empty on the Hub: it carries an initial commit
  // and a `main` pointing at it, which is what makes an upload to a
  // just-created repo a second commit rather than the first.
  const sha = mintSha(minter)
  await db.hfCommit.create({
    data: {
      tenant,
      repo: repoKey(kind, namespace, name),
      sha,
      message: 'initial commit',
      createdAt: options.now,
      seq: minter.next('commit_seq'),
    },
  })
  await db.hfRef.create({
    data: {
      tenant,
      repo: repoKey(kind, namespace, name),
      refType: 'branch',
      name: DEFAULT_REVISION,
      sha,
    },
  })
  return repo
}

export interface Change {
  path: string
  content?: Uint8Array
  deleted?: boolean
  deletedFolder?: boolean
}

/**
 * Apply a commit: copy the parent's rows forward, then the changes on top.
 *
 * Copying is what makes a tag a pointer rather than a snapshot copy: a ref
 * that still names the parent sha keeps reading the parent's rows, untouched
 * by this commit. It is O(tree) per commit, which is right for a fake whose
 * fixtures are a few dozen small files and wrong for anything larger.
 */
export async function commitChanges(
  db: C,
  tenant: string,
  repo: string,
  branch: string,
  changes: Change[],
  message: string,
  description: string,
  now: string,
  minter: Minter,
): Promise<string> {
  const parent = (await resolveRevision(db, tenant, repo, branch)) ?? ''
  const sha = mintSha(minter)
  await db.hfCommit.create({
    data: {
      tenant,
      repo,
      sha,
      message,
      description,
      createdAt: now,
      parent,
      seq: minter.next('commit_seq'),
    },
  })
  const carried = new Map<string, Blob>()
  if (parent !== '') {
    for (const blob of await blobsAt(db, tenant, repo, parent)) carried.set(blob.path, blob)
  }
  for (const change of changes) {
    if (change.deletedFolder === true) {
      const prefix = `${rstripSlash(change.path)}/`
      for (const path of [...carried.keys()]) {
        if (path.startsWith(prefix)) carried.delete(path)
      }
      continue
    }
    if (change.deleted === true) {
      carried.delete(change.path)
      continue
    }
    const content = change.content ?? new Uint8Array(0)
    carried.set(change.path, {
      tenant,
      repo,
      sha,
      path: change.path,
      content,
      oid: gitOid(content),
      lfsOid: '',
      pointerSize: 0,
      lastCommit: sha,
      lastModified: now,
      seq: minter.next('blob'),
    })
  }
  for (const blob of [...carried.values()].sort((a, b) => (a.path < b.path ? -1 : 1))) {
    await db.hfBlob.create({
      data: {
        tenant,
        repo,
        sha,
        path: blob.path,
        content: Buffer.from(blob.content),
        oid: blob.oid,
        lfsOid: blob.lfsOid,
        pointerSize: blob.pointerSize,
        lastCommit: blob.lastCommit,
        lastModified: blob.lastModified,
        seq: blob.seq,
      },
    })
  }
  await db.hfRef.upsert({
    where: { tenant_repo_refType_name: { tenant, repo, refType: 'branch', name: branch } },
    update: { sha },
    create: { tenant, repo, refType: 'branch', name: branch, sha },
  })
  return sha
}
