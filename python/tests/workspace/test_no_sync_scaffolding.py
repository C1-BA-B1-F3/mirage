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

import importlib

import mirage.workspace.types as t
from mirage.workspace import Workspace


def test_workspace_has_no_sync_attribute():
    assert not hasattr(Workspace, "sync"), (
        "Workspace.sync() was a no-op (DirtyTracker always empty); "
        "should be removed in Phase 1 cleanup."
    )


def test_sync_policy_enum_removed():
    assert not hasattr(t, "SyncPolicy"), "SyncPolicy removed in Phase 1."
    assert not hasattr(t, "SyncResult"), "SyncResult removed in Phase 1."
    assert not hasattr(t, "Inode"), "Inode removed in Phase 1."


def test_dirty_tracker_module_removed():
    try:
        importlib.import_module("mirage.workspace.tracker")
    except ModuleNotFoundError:
        return
    raise AssertionError("mirage.workspace.tracker should be deleted.")
