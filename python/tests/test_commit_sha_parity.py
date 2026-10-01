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

from mirage.core.github.constants import COMMIT_SHA as GITHUB_COMMIT_SHA
from mirage.core.hf_hub.constants import COMMIT_SHA as HF_COMMIT_SHA

REPO = pathlib.Path(__file__).resolve().parents[2]
TS_COPIES = (
    REPO
    / "typescript"
    / "packages"
    / "core"
    / "src"
    / "core"
    / "github"
    / "constants.ts",
    REPO
    / "typescript"
    / "packages"
    / "node"
    / "src"
    / "core"
    / "hf_hub"
    / "constants.ts",
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


def _ts_copy(path: pathlib.Path) -> re.Pattern[str]:
    match = TS_LITERAL.search(path.read_text(encoding="utf-8"))
    assert match is not None, f"no COMMIT_SHA literal in {path}"
    assert match.group(2) == "", f"{path} adds flags {match.group(2)!r}"
    source = match.group(1)
    if source.endswith("$"):
        source = source[:-1] + r"\Z"
    return re.compile(source)


def _copies() -> dict[str, re.Pattern[str]]:
    return {
        "python github": GITHUB_COMMIT_SHA,
        "python hf_hub": HF_COMMIT_SHA,
        **{str(path.relative_to(REPO)): _ts_copy(path) for path in TS_COPIES},
    }


def _python_accepts(pattern: re.Pattern[str], sample: str) -> bool:
    return pattern.fullmatch(sample) is not None


def _ts_accepts(pattern: re.Pattern[str], sample: str) -> bool:
    return pattern.search(sample) is not None


@pytest.mark.parametrize("sample", ACCEPTED + REFUSED)
def test_every_commit_sha_copy_gives_the_same_answer(sample):
    """Four copies of one rule: which ref pins a mount to a commit.

    Python matches with ``fullmatch`` and TypeScript with an anchored
    ``RegExp.test``, so each copy is asked the way its host asks it (a
    JavaScript ``$`` is the end of input, Python's ``\\Z``). A
    copy that drifts (one length changed, an anchor dropped, a case flag
    added) would pin a branch on one host and not the other.
    """
    expected = sample in ACCEPTED
    for name, pattern in _copies().items():
        ask = _python_accepts if name.startswith("python") else _ts_accepts
        assert ask(pattern, sample) is expected, (name, sample)
