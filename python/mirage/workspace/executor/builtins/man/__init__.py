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

from mirage.workspace.executor.builtins.man.man import (
    _command_entry,
    _render_man_index,
    _render_page,
    handle_man,
)
from mirage.workspace.executor.builtins.man.types import ManEntry

__all__ = [
    "ManEntry",
    "_command_entry",
    "_render_man_index",
    "_render_page",
    "handle_man",
]
