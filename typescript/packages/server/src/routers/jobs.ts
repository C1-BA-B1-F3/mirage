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

import type { FastifyInstance } from 'fastify'
import { toBriefDict, type JobBriefDict, type JobEntry, type JobTable } from '../jobs.ts'
import type { JsonValue } from '@struktoai/mirage-core/types'

export interface JobsRoutesDeps {
  jobs: JobTable
}

interface JobIdParams {
  id: string
}

interface JobsListQuery {
  workspaceId?: string
}

interface WaitBody {
  timeoutS?: number
}

interface JobDetailDict extends JobBriefDict {
  result: JsonValue
  error: string | null
}

function toDetailDict(entry: JobEntry): JobDetailDict {
  const brief = toBriefDict(entry)
  return { ...brief, result: entry.result, error: entry.error }
}

export function registerJobsRoutes(app: FastifyInstance, deps: JobsRoutesDeps): void {
  app.get<{ Querystring: JobsListQuery }>('/v1/jobs', async (req) => {
    return (await deps.jobs.list(req.query.workspaceId)).map(toBriefDict)
  })

  app.get<{ Params: JobIdParams }>('/v1/jobs/:id', async (req, reply) => {
    const { id } = req.params
    const entry = await deps.jobs.store.get(id)
    if (entry === null) return reply.status(404).send({ detail: 'job not found' })
    return toDetailDict(entry)
  })

  app.post<{ Params: JobIdParams; Body: WaitBody | null }>(
    '/v1/jobs/:id/wait',
    async (req, reply) => {
      const { id } = req.params
      if ((await deps.jobs.store.get(id)) === null)
        return reply.status(404).send({ detail: 'job not found' })
      const entry = await deps.jobs.wait(id, req.body?.timeoutS)
      return toDetailDict(entry)
    },
  )

  app.delete<{ Params: JobIdParams }>('/v1/jobs/:id', async (req, reply) => {
    const { id } = req.params
    if ((await deps.jobs.store.get(id)) === null)
      return reply.status(404).send({ detail: 'job not found' })
    return { jobId: id, canceled: await deps.jobs.cancel(id) }
  })
}
