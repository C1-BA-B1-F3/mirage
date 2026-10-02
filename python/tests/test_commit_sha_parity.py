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

import pathlib
import re

import pytest

from mirage.core.github.constants import COMMIT_SHA

TS_CONSTANTS = (
    pathlib.Path(__file__).resolve().parents[2]
    / "typescript/packages/core/src/core/github/constants.ts"
)
TS_LITERAL = re.compile(
    r"^export const COMMIT_SHA = /(.+)/([a-z]*)$", re.MULTILINE
)
ACCEPTED = ("0" * 40, "f" * 40, "0123456789abcdef" * 4, "a" * 64)
REFUSED = (
    "",
    "a" * 39,
    "a" * 41,
    "a" * 63,
    "a" * 65,
    "a" * 104,
    "A" * 40,
    "g" * 40,
    "a" * 40 + "\n",
    " " + "a" * 40,
    "main",
)


def _ts_commit_sha() -> re.Pattern[str]:
    match = TS_LITERAL.search(TS_CONSTANTS.read_text(encoding="utf-8"))
    assert match is not None, f"no COMMIT_SHA literal in {TS_CONSTANTS}"
    assert match.group(2) == "", f"COMMIT_SHA adds flags {match.group(2)!r}"
    source = match.group(1)
    if source.endswith("$"):
        source = source[:-1] + r"\Z"
    return re.compile(source)


@pytest.mark.parametrize("sample", ACCEPTED + REFUSED)
def test_python_and_typescript_commit_sha_give_the_same_answer(sample):
    """Python's ``fullmatch`` and TypeScript's anchored ``RegExp.test``.

    Each copy is asked the way its host asks it (a JavaScript ``$`` is the
    end of input, Python's ``\\Z``). A copy that drifts (one length
    changed, an anchor dropped, a case flag added) would pin a branch on
    one host and not the other.
    """
    expected = sample in ACCEPTED
    assert (COMMIT_SHA.fullmatch(sample) is not None) is expected
    assert (_ts_commit_sha().search(sample) is not None) is expected
