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

from mirage.vfs.disk import DiskVFS
from mirage.vfs.errors import VFSConfigError


@pytest.mark.parametrize("value", ["no", 1, None])
def test_folder_versions_must_be_a_boolean(tmp_path, value):
    root = tmp_path / "root"
    with pytest.raises(VFSConfigError) as exc:
        DiskVFS(str(root), folder_versions=value)
    assert str(exc.value) == "disk: folder_versions: must be a boolean"
    assert not root.exists()
