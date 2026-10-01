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

from mirage.vfs.gridfs.config import GridFSConfig


def test_config_defaults():
    config = GridFSConfig(uri="mongodb://localhost:27017", database="db")
    assert config.bucket == "fs"
    assert config.key_prefix is None
    assert config.chunk_size_bytes is None


def test_config_normalizes_key_prefix():
    config = GridFSConfig(
        uri="mongodb://localhost:27017",
        database="db",
        key_prefix="/team/reports/",
    )
    assert config.key_prefix == "team/reports/"


def test_config_empty_key_prefix_becomes_none():
    config = GridFSConfig(
        uri="mongodb://localhost:27017", database="db", key_prefix=""
    )
    assert config.key_prefix is None
