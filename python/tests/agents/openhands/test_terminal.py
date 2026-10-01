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

import pytest

pytest.importorskip("openhands")

from openhands.sdk.tool import list_registered_tools

from mirage.agents.openhands import (
    MirageWorkspace,
    register_mirage_terminal,
)
from mirage.types import MountMode
from mirage.vfs.ram import RAMVFS
from mirage.workspace import Workspace


def test_register_mirage_terminal_uses_tool_definition():
    backing = Workspace({"/": RAMVFS()}, mode=MountMode.WRITE)
    with MirageWorkspace(workspace=backing) as workspace:
        name = register_mirage_terminal(workspace, "mirage_terminal_test")
        assert name in list_registered_tools()
