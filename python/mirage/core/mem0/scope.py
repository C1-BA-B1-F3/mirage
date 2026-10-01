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

from mirage.core.hierarchy.codec import JSON_NAME
from mirage.core.hierarchy.scope import Scope, Slot, make_detect_scope
from mirage.types import ContentType

# The mount is one flat directory of memory files; which memories exist
# is a function of the configured scope filter, not of the path.
SCOPES = (
    Scope(
        kind="memory",
        segments=(Slot("memory_id", JSON_NAME),),
        leaf=True,
        filetype=ContentType.JSON,
    ),
)

detect_scope = make_detect_scope(SCOPES)
