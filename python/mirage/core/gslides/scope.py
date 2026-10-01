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

from mirage.core.google.constants import CORPUS
from mirage.core.gslides.constants import FILE_NAME
from mirage.core.hierarchy.scope import Scope, Slot, make_detect_scope
from mirage.types import ContentType

# One description of the tree: readdir, stat, read and unlink all classify
# through it, so the file surface and the write surface cannot disagree
# about what a path means.
SCOPES = (
    Scope(kind="corpus", segments=(Slot("corpus", CORPUS),), probed=False),
    Scope(
        kind="file",
        segments=(
            Slot("corpus", CORPUS),
            Slot("name", FILE_NAME, id_key="file_id"),
        ),
        leaf=True,
        filetype=ContentType.JSON,
    ),
)

detect_scope = make_detect_scope(SCOPES)
