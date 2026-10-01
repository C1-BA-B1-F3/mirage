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
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mirage.workspace.node.execute_node import execute_node
    from mirage.workspace.node.provision_node import provision_node
    from mirage.workspace.node.run_tree import run_command_tree

_EXPORTS: dict[str, tuple[str, ...]] = {
    "mirage.workspace.node.execute_node": ("execute_node", ),
    "mirage.workspace.node.provision_node": ("provision_node", ),
    "mirage.workspace.node.run_tree": ("run_command_tree", ),
}
_MODULE_OF = {
    name: module
    for module, names in _EXPORTS.items()
    for name in names
}

__all__ = ["execute_node", "provision_node", "run_command_tree"]


def __getattr__(name: str) -> Any:
    module = _MODULE_OF.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(module), name)
    globals()[name] = value
    return value
