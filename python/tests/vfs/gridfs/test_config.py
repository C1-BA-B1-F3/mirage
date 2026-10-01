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

from mirage.vfs.gridfs.config import GridFSConfig


@pytest.mark.parametrize(
    "raw,normalized",
    [("/team/reports/", "team/reports/"), ("", None), (None, None)],
)
def test_key_prefix_is_normalized(raw, normalized):
    config = GridFSConfig(
        uri="mongodb://localhost:27017", database="db", key_prefix=raw
    )
    assert config.key_prefix == normalized
