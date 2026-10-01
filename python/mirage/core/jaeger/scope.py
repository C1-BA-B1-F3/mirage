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

from mirage.core.hierarchy.codec import Codec
from mirage.core.hierarchy.scope import Scope, Slot, make_detect_scope
from mirage.core.jaeger.client import is_trace_id
from mirage.types import ContentType

OPERATIONS_FILE = "operations.json"
TOP_LEVEL_DIRS = ["services"]

# A malformed id cannot name an existing trace, so it fails the scope
# match outright and reads as ENOENT rather than the API's 400 "invalid
# length for TraceID".
TRACE_FILE = Codec(suffix=".json", validate=is_trace_id)

# The tree is service-scoped because Jaeger's search API requires a
# service: there is no endpoint that lists every trace.
SCOPES = (
    Scope(kind="services", segments=("services",), probed=False),
    Scope(kind="service", segments=("services", Slot("service"))),
    Scope(
        kind="operations",
        segments=("services", Slot("service"), OPERATIONS_FILE),
        leaf=True,
        filetype=ContentType.JSON,
    ),
    Scope(kind="traces", segments=("services", Slot("service"), "traces")),
    Scope(
        kind="trace",
        segments=(
            "services",
            Slot("service"),
            "traces",
            Slot("trace_id", TRACE_FILE),
        ),
        leaf=True,
        filetype=ContentType.JSON,
    ),
)

detect_scope = make_detect_scope(SCOPES)
