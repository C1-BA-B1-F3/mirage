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

import { mkdir, rm, stat } from 'node:fs/promises'
import * as nodeFs from 'node:fs'
import { join, resolve, sep } from 'node:path'
import git from 'isomorphic-git'
import { PathOutsideRootError, validatePathSegment } from '../paths.ts'

export type FsClient = Parameters<typeof git.init>[0]['fs']

export interface GitRepo {
  fs: FsClient
  gitdir: string
}

export interface VersionBackend {
  openRepo(workspaceId: string): Promise<GitRepo>
  hasRepo(workspaceId: string): Promise<boolean>
  dropRepo(workspaceId: string): Promise<void>
}

export class LocalBackend implements VersionBackend {
  constructor(private readonly root: string) {}

  private gitdirOf(workspaceId: string): string {
    validatePathSegment(workspaceId)
    const root = resolve(this.root)
    const gitdir = resolve(root, workspaceId)
    if (!gitdir.startsWith(root + sep)) {
      throw new PathOutsideRootError(`path escapes the configured root: ${workspaceId}`)
    }
    return gitdir
  }

  async openRepo(workspaceId: string): Promise<GitRepo> {
    const gitdir = this.gitdirOf(workspaceId)
    const fs = nodeFs as unknown as FsClient
    if (!(await this.hasRepo(workspaceId))) {
      await mkdir(gitdir, { recursive: true })
      await git.init({ fs, dir: gitdir, bare: true, defaultBranch: 'main' })
    }
    return { fs, gitdir }
  }
  /**
   * Whether a workspace has committed anything, without creating. An id
   * that is not one safe path segment can never have had a repo, so it
   * has none rather than an error.
   */
  async hasRepo(workspaceId: string): Promise<boolean> {
    let gitdir: string
    try {
      gitdir = this.gitdirOf(workspaceId)
    } catch (err) {
      if (err instanceof PathOutsideRootError) return false
      throw err
    }
    try {
      return (await stat(join(gitdir, 'objects'))).isDirectory()
    } catch (error: unknown) {
      if (!(error instanceof Error) || !('code' in error) || error.code !== 'ENOENT') throw error
      return false
    }
  }

  /** Delete one workspace's version repo, when it has one. */
  async dropRepo(workspaceId: string): Promise<void> {
    if (await this.hasRepo(workspaceId)) {
      await rm(this.gitdirOf(workspaceId), { recursive: true, force: true })
    }
  }
}
