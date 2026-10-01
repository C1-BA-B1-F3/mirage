# ========= Copyright 2026 @ Strukto.AI All Rights Reserved. =========
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ========= Copyright 2026 @ Strukto.AI All Rights Reserved. =========

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from mirage.server.io_serde import io_result_to_dict
from mirage.server.jobs import JobEntry

router = APIRouter(prefix="/v1/jobs")


class JobBrief(BaseModel):
    job_id: str
    workspace_id: str
    command: str
    status: str
    submitted_at: float
    started_at: float | None = None
    finished_at: float | None = None


class JobDetail(JobBrief):
    result: dict[str, Any] | None = None
    error: str | None = None


class WaitRequest(BaseModel):
    timeout_s: float | None = None


class CancelResponse(BaseModel):
    job_id: str
    canceled: bool


def _to_brief(entry: JobEntry) -> JobBrief:
    return JobBrief(
        job_id=entry.id,
        workspace_id=entry.workspace_id,
        command=entry.command,
        status=entry.status.value,
        submitted_at=entry.submitted_at,
        started_at=entry.started_at,
        finished_at=entry.finished_at,
    )


async def _to_detail(entry: JobEntry) -> JobDetail:
    result_dict: dict[str, Any] | None = None
    if entry.result is not None:
        result_dict = await io_result_to_dict(entry.result)
    return JobDetail(
        job_id=entry.id,
        workspace_id=entry.workspace_id,
        command=entry.command,
        status=entry.status.value,
        submitted_at=entry.submitted_at,
        started_at=entry.started_at,
        finished_at=entry.finished_at,
        result=result_dict,
        error=entry.error,
    )


def _require_job(request: Request, job_id: str) -> JobEntry:
    table = request.app.state.jobs
    if job_id not in table:
        raise HTTPException(status_code=404, detail="job not found")
    return table.get(job_id)


@router.get("", response_model=list[JobBrief])
async def list_jobs(
    request: Request, workspace_id: str | None = Query(None)
) -> list[JobBrief]:
    return [
        _to_brief(j)
        for j in request.app.state.jobs.list(workspace_id=workspace_id)
    ]


@router.get("/{job_id}", response_model=JobDetail)
async def get_job(job_id: str, request: Request) -> JobDetail:
    return await _to_detail(_require_job(request, job_id))


@router.post("/{job_id}/wait", response_model=JobDetail)
async def wait_job(
    job_id: str, req: WaitRequest, request: Request
) -> JobDetail:
    table = request.app.state.jobs
    if job_id not in table:
        raise HTTPException(status_code=404, detail="job not found")
    entry = await table.wait(job_id, timeout=req.timeout_s)
    return await _to_detail(entry)


@router.delete("/{job_id}", response_model=CancelResponse)
async def cancel_job(job_id: str, request: Request) -> CancelResponse:
    table = request.app.state.jobs
    if job_id not in table:
        raise HTTPException(status_code=404, detail="job not found")
    canceled = table.cancel(job_id)
    return CancelResponse(job_id=job_id, canceled=canceled)
