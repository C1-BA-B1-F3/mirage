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

from mirage.types import MountMode
from mirage.vfs.ram import RAMVFS
from mirage.workspace import Workspace

# Pinned against GNU bash 5.2.37: `[` is a command, so every operator the
# grammar folds into a `[ ... ]` test reaches it as an operand word, and test
# refuses the ones it does not know rather than never seeing them.


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "line, out, err",
    [
        ("[ a == a ] && echo y", "y\n", ""),
        ("[ $ ] && echo y", "y\n", ""),
        (
            "[ a =~ a ]; echo $?",
            "2\n",
            "bash: [: =~: binary operator expected\n",
        ),
        (
            "[ 1 + 1 ]; echo $?",
            "2\n",
            "bash: [: +: binary operator expected\n",
        ),
        (
            "[ a += b ]; echo $?",
            "2\n",
            "bash: [: +=: binary operator expected\n",
        ),
        (
            "[ a -= b ]; echo $?",
            "2\n",
            "bash: [: -=: binary operator expected\n",
        ),
    ],
)
async def test_every_operator_reaches_test_as_a_word(line, out, err):
    ws = Workspace({"/data": RAMVFS()}, mode=MountMode.WRITE)
    io = await ws.shell(line)
    assert (await io.stdout_str(), await io.stderr_str()) == (out, err)
