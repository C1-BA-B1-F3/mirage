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

import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from mirage import Workspace
from mirage.concurrency.limiter import run_blocking
from mirage.config import resolve_secrets
from mirage.secrets.errors import SecretsError
from mirage.server.clone import (
    build_override_mounts,
    clone_workspace_with_override,
)
from mirage.server.paths import PathOutsideRootError, resolve_within_root
from mirage.server.schemas import (
    CloneWorkspaceRequest,
    CreateWorkspaceRequest,
    DeleteWorkspaceResponse,
    LoadWorkspaceRequest,
    SnapshotWorkspaceRequest,
    SnapshotWorkspaceResponse,
    WorkspaceBrief,
    WorkspaceDetail,
)
from mirage.server.summary import make_brief, make_detail
from mirage.utils.ids import new_workspace_id
from mirage.workspace.store import DiskWorkspaceStateStore
from mirage.workspace.store.disk import DOT_IDS

router = APIRouter(prefix="/v1/workspaces")


def _refuse_dot_id(workspace_id: str | None) -> None:
    """Refuse an id that would name the state root, not a workspace.

    Args:
        workspace_id (str | None): the id the request names, if any.
    """
    if workspace_id is not None and workspace_id in DOT_IDS:
        raise HTTPException(
            status_code=400, detail=f"invalid workspace id: {workspace_id!r}"
        )


@router.post("", response_model=WorkspaceDetail, status_code=201)
async def create_workspace(
    req: CreateWorkspaceRequest, request: Request
) -> WorkspaceDetail:
    registry = request.app.state.registry
    if req.id is not None and req.id in registry:
        raise HTTPException(
            status_code=409, detail=f"workspace id already exists: {req.id!r}"
        )
    try:
        # Map runtime entries construct their instances here, so a bad
        # entry (a wasi build dir that does not exist, an unknown
        # option) fails the create like any other config mistake.
        kwargs = (await resolve_secrets(req.config)).to_workspace_kwargs()
    except (
        FileNotFoundError,
        ImportError,
        SecretsError,
        ValueError,
        TypeError,
    ) as e:
        raise HTTPException(status_code=400, detail=str(e))
    # The registry id and the state-store scope must be the same identity,
    # so resolve it before construction: explicit REST id, then the
    # config's workspace_id, then a fresh mint.
    wid = (
        req.id
        if req.id is not None
        else kwargs.get("workspace_id") or new_workspace_id()
    )
    _refuse_dot_id(wid)
    kwargs["workspace_id"] = wid
    # Daemon default is disk (a created workspace survives restart with
    # zero infrastructure, like git init); the library default stays ram.
    # A config with an explicit store: block always wins.
    if "store" not in kwargs:
        kwargs["store"] = DiskWorkspaceStateStore(
            str(request.app.state.state_root)
        )
        kwargs["owns_store"] = True
    try:
        ws = Workspace(**kwargs)
    except (FileNotFoundError, ImportError, SecretsError, ValueError) as e:
        # Construction failures (a wasi build dir that does not exist, a
        # missing runtime extra, a `secrets:` block naming a source the
        # host cannot resolve) are the caller's to fix, not a 500.
        raise HTTPException(status_code=400, detail=str(e))
    try:
        for prefix, (
            backend,
            mountpoint,
        ) in req.config.kernel_mounts().items():
            await run_blocking(
                ws.add_fuse_mount, prefix, mountpoint, backend=backend
            )
        entry = registry.add(ws, workspace_id=wid)
    except ValueError as e:
        await ws.close()
        raise HTTPException(status_code=409, detail=str(e))
    except Exception:
        await ws.close()
        raise
    return await make_detail(entry)


@router.get("", response_model=list[WorkspaceBrief])
async def list_workspaces(request: Request) -> list[WorkspaceBrief]:
    return [make_brief(e) for e in request.app.state.registry.list()]


@router.get("/{workspace_id}", response_model=WorkspaceDetail)
async def get_workspace(
    workspace_id: str, request: Request, verbose: bool = Query(False)
) -> WorkspaceDetail:
    registry = request.app.state.registry
    if workspace_id not in registry:
        raise HTTPException(status_code=404, detail="workspace not found")
    return await make_detail(registry.get(workspace_id), verbose=verbose)


@router.delete("/{workspace_id}", response_model=DeleteWorkspaceResponse)
async def delete_workspace(
    workspace_id: str, request: Request
) -> DeleteWorkspaceResponse:
    registry = request.app.state.registry
    if workspace_id not in registry:
        raise HTTPException(status_code=404, detail="workspace not found")
    backend = request.app.state.version_backend
    try:
        await registry.remove(
            workspace_id,
            cleanup=lambda: run_blocking(backend.drop_repo, workspace_id),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"workspace delete failed: {exc}"
        ) from exc
    return DeleteWorkspaceResponse(id=workspace_id, closed_at=time.time())


@router.post(
    "/{workspace_id}/clone", response_model=WorkspaceDetail, status_code=201
)
async def clone_workspace(
    workspace_id: str, req: CloneWorkspaceRequest, request: Request
) -> WorkspaceDetail:
    registry = request.app.state.registry
    if workspace_id not in registry:
        raise HTTPException(status_code=404, detail="workspace not found")
    _refuse_dot_id(req.id)
    if req.id is not None and req.id in registry:
        raise HTTPException(
            status_code=409, detail=f"workspace id already exists: {req.id!r}"
        )
    src_entry = registry.get(workspace_id)
    try:
        new_ws = await src_entry.runner.call(
            clone_workspace_with_override(src_entry.runner.ws, req.override)
        )
    except (SecretsError, ValueError) as e:
        # An override naming a source the host cannot resolve, or a
        # block the schema refuses, is the caller's mistake -- the
        # answer create, load and the historical clone already give.
        raise HTTPException(status_code=400, detail=str(e))
    try:
        entry = registry.add(new_ws, workspace_id=req.id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return await make_detail(entry)


@router.post(
    "/{workspace_id}/snapshot", response_model=SnapshotWorkspaceResponse
)
async def snapshot_workspace(
    workspace_id: str, req: SnapshotWorkspaceRequest, request: Request
) -> SnapshotWorkspaceResponse:
    registry = request.app.state.registry
    if workspace_id not in registry:
        raise HTTPException(status_code=404, detail="workspace not found")
    entry = registry.get(workspace_id)
    try:
        target = await run_blocking(
            resolve_within_root, request.app.state.snapshot_root, req.path
        )
    except PathOutsideRootError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await run_blocking(target.parent.mkdir, parents=True, exist_ok=True)
    await entry.runner.call(entry.runner.ws.snapshot(str(target)))
    info = await run_blocking(target.stat)
    return SnapshotWorkspaceResponse(
        id=workspace_id, path=str(target), size=info.st_size
    )


@router.post("/load", response_model=WorkspaceDetail, status_code=201)
async def load_workspace(
    req: LoadWorkspaceRequest, request: Request
) -> WorkspaceDetail:
    registry = request.app.state.registry
    try:
        safe_path = await run_blocking(
            resolve_within_root, request.app.state.snapshot_root, req.path
        )
    except PathOutsideRootError as e:
        raise HTTPException(status_code=400, detail=str(e))
    _refuse_dot_id(req.id)
    if req.id is not None and req.id in registry:
        raise HTTPException(
            status_code=409, detail=f"workspace id already exists: {req.id!r}"
        )
    secrets = _build_load_secrets(req.override)
    try:
        # An override mount's credential may be a pointer at one of
        # these declarations; a container the constructor will reject
        # is left for it to reject.
        mounts = await build_override_mounts(req.override, secrets)
    except (KeyError, TypeError, ValueError, SecretsError) as e:
        # An override naming a VFS the daemon cannot build (an
        # unknown name, an unloadable ref, a ref that is not a VFS,
        # a secrets source it cannot resolve) is the caller's mistake,
        # the answer the TypeScript daemon gives too; it used to escape
        # as a 500.
        raise HTTPException(
            status_code=400, detail=f"override build failed: {e}"
        )
    try:
        ws = await Workspace.load(
            str(safe_path), mounts=mounts, secrets=secrets
        )
    except FileNotFoundError:
        raise HTTPException(
            status_code=400, detail=f"snapshot not found: {req.path}"
        )
    except (SecretsError, ValueError) as e:
        # A secrets override naming an unknown source, or one whose
        # optional dependency is absent, is a bad request like any
        # other override the deployment got wrong.
        raise HTTPException(status_code=400, detail=str(e))
    try:
        entry = registry.add(ws, workspace_id=req.id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return await make_detail(entry)


def _build_load_secrets(
    override: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """The `secrets:` declarations a load override supplies.

    A snapshot never carries the block, because it is the deployment's
    credentials, so a restored pointer at a declared instance needs it
    named here -- the same reason a redacted mount needs `mounts`.
    """
    if not override:
        return None
    # Passed through as it arrived, even when it is not a mapping: the
    # constructor is the one place that judges the container, and
    # filtering here turned a bad override into a successful load whose
    # every restored pointer was unresolvable.
    return override.get("secrets")
