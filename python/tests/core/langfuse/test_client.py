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

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from langfuse.api.commons.types.trace_with_full_details import (
    TraceWithFullDetails,
)
from langfuse.api.core.pydantic_utilities import parse_obj_as

from mirage.core.langfuse.client import fetch_trace


@pytest.mark.asyncio
async def test_fetch_trace_keeps_the_api_numbers():
    trace = parse_obj_as(
        TraceWithFullDetails,
        {
            "id": "trace-alpha",
            "timestamp": "2026-01-01T00:00:00.000Z",
            "htmlPath": "/project/p/traces/trace-alpha",
            "tags": [],
            "public": False,
            "environment": "default",
            "latency": 1,
            "totalCost": 0.25,
            "observations": [],
            "scores": [],
            "metadata": {"ratio": 0.5, "count": 2},
        },
    )
    api = MagicMock()
    api.trace.get = AsyncMock(return_value=trace)

    data = await fetch_trace(api, "trace-alpha")

    assert json.dumps(data["latency"]) == "1"
    assert json.dumps(data["totalCost"]) == "0.25"
    assert data["metadata"] == {"ratio": 0.5, "count": 2}
