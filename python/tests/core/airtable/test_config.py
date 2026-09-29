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
from pydantic import ValidationError

from mirage.core.airtable.config import AirtableConfig


def test_defaults_point_at_the_public_api():
    config = AirtableConfig(token="t")
    assert config.base_url == "https://api.airtable.com/v0"
    assert config.max_read_records == 10_000
    assert config.requests_per_second == 5.0
    assert config.base_ids is None


def test_a_misspelled_key_is_refused():
    with pytest.raises(ValidationError, match="base_idz"):
        AirtableConfig(token="t", base_idz=["appX"])


@pytest.mark.parametrize("field, value", [
    ("max_read_records", 0),
    ("requests_per_second", 0),
])
def test_bounds_are_positive(field, value):
    with pytest.raises(ValidationError):
        AirtableConfig(token="t", **{field: value})
