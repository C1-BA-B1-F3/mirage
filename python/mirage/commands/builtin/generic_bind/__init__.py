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
    from mirage.commands.builtin.generic_bind.adapter import CommandIO
    from mirage.commands.builtin.generic_bind.factory import (
        make_generic_commands, with_read_cache, with_stat_cache)
    from mirage.commands.builtin.generic_bind.provision import (
        default_provision, make_copy_provision, make_file_read_provision,
        make_head_tail_provision, make_jq_provision, make_search_provision,
        make_sed_provision, make_transform_provision, metadata_provision,
        pure_provision, write_metadata_provision)
    from mirage.utils.glob_walk import make_resolve_glob
    from mirage.vfs.types import DuOps

_EXPORTS: dict[str, tuple[str, ...]] = {
    "mirage.commands.builtin.generic_bind.adapter": ("CommandIO", ),
    "mirage.commands.builtin.generic_bind.factory":
    ("make_generic_commands", "with_read_cache", "with_stat_cache"),
    "mirage.commands.builtin.generic_bind.provision":
    ("default_provision", "make_copy_provision", "make_file_read_provision",
     "make_head_tail_provision", "make_jq_provision", "make_search_provision",
     "make_sed_provision", "make_transform_provision", "metadata_provision",
     "pure_provision", "write_metadata_provision"),
    "mirage.utils.glob_walk": ("make_resolve_glob", ),
    "mirage.vfs.types": ("DuOps", ),
}
_MODULE_OF = {
    name: module
    for module, names in _EXPORTS.items()
    for name in names
}

__all__ = [
    "CommandIO",
    "DuOps",
    "default_provision",
    "make_copy_provision",
    "make_file_read_provision",
    "make_generic_commands",
    "make_head_tail_provision",
    "make_jq_provision",
    "make_resolve_glob",
    "make_search_provision",
    "make_sed_provision",
    "make_transform_provision",
    "metadata_provision",
    "pure_provision",
    "with_read_cache",
    "with_stat_cache",
    "write_metadata_provision",
]


def __getattr__(name: str) -> Any:
    module = _MODULE_OF.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(module), name)
    globals()[name] = value
    return value
