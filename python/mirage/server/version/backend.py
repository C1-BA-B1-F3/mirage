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

import shutil
from pathlib import Path
from typing import Protocol

from dulwich.repo import Repo

from mirage.server.paths import (
    PathOutsideRootError,
    resolve_within_root,
    validate_path_segment,
)


class VersionBackend(Protocol):
    def open_repo(self, workspace_id: str) -> Repo: ...

    def has_repo(self, workspace_id: str) -> bool: ...

    def drop_repo(self, workspace_id: str) -> None: ...


class LocalBackend:
    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    def _path(self, workspace_id: str) -> Path:
        return resolve_within_root(
            self._root, validate_path_segment(workspace_id)
        )

    def open_repo(self, workspace_id: str) -> Repo:
        path = self._path(workspace_id)
        if (path / "objects").is_dir():
            return Repo(str(path))
        path.mkdir(parents=True, exist_ok=True)
        return Repo.init_bare(str(path))

    def has_repo(self, workspace_id: str) -> bool:
        """Whether a workspace has committed anything, without creating.

        An id that is not one safe path segment can never have had a
        repo, so it has none rather than an error.

        Args:
            workspace_id (str): the workspace asked about.
        """
        try:
            path = self._path(workspace_id)
        except PathOutsideRootError:
            return False
        return (path / "objects").is_dir()

    def drop_repo(self, workspace_id: str) -> None:
        """Delete one workspace's version repo, when it has one.

        Args:
            workspace_id (str): the workspace being deleted.
        """
        if self.has_repo(workspace_id):
            shutil.rmtree(self._path(workspace_id))
