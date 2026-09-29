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

import { Prisma, PrismaClient } from '../../generated/github/index.js'
import type { Dmmf, Fake } from '../kit/typescript/index.ts'
import { config } from './config.ts'
import type { C } from './config.ts'
import { githubRoutes } from './routes.ts'
import { seedRepos } from './seed.ts'

export const githubFake: Fake<C> = {
  config,
  client: PrismaClient,
  dmmf: Prisma.dmmf as unknown as Dmmf,
  seedRoots: {
    repos: 'GithubRepo',
    settings: 'GithubSetting',
    issues: 'GithubIssue',
    comments: 'GithubComment',
  },
  // A repository's files come from the directory its row names, and every
  // repository starts with the same workflows, checks, statuses and one run.
  // Neither is stateable in a fixture, so both happen here.
  afterSeed: seedRepos,
  routes: githubRoutes,
}
