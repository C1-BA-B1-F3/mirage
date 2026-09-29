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

from mirage.commands.builtin.utils.copy import landing_name
from mirage.types import PathSpec


@pytest.mark.parametrize("typed,virtual,name", [
    ("al", "/data/a.txt", "al"),
    ("dir/al/", "/data/a.txt", "al"),
    ("/data/x/y", "/data/x/y", "y"),
    ("", "/data/sub", "sub"),
    (".", "/data/sub", "sub"),
    ("sub/..", "/data", "data"),
])
def test_landing_name_is_the_operand_as_typed(typed, virtual, name):
    # GNU names a source inside a directory after the operand as typed,
    # so a followed link lands under its own name; the empty name, `.`
    # and `..` name no entry, so they keep what they resolve to.
    src = PathSpec(virtual=virtual,
                   directory=virtual.rsplit("/", 1)[0] or "/",
                   vfs_path=virtual.strip("/"),
                   raw_path=typed)
    assert landing_name(src) == name
