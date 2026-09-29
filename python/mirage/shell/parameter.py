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

from mirage.shell.constants import PARAMETER_NAME


def scan_parameter(text: str, start: int) -> tuple[str, int] | None:
    """Recognize a plain dollar reference, returning its name and end.

    Names use Bash's ASCII identifier grammar. Unbraced positionals
    consume one digit; braces permit multiple digits. Special parameters
    consume one character. The caller owns quoting and must only scan a
    live dollar. Complex braced operators remain the expansion parser's
    responsibility and return None here, as do non-reference dollars.

    Args:
        text (str): shell source containing the reference.
        start (int): character offset of the live dollar.
    """
    if start < 0 or start >= len(text) or text[start] != "$":
        return None
    begin = start + 1
    braced = text[begin:begin + 1] == "{"
    if braced:
        begin += 1
    match = PARAMETER_NAME.match(text, begin)
    if match is None:
        return None
    end = match.end()
    if not braced and "0" <= text[begin] <= "9":
        end = begin + 1
    name = text[begin:end]
    if braced:
        if text[end:end + 1] != "}":
            return None
        end += 1
    return name, end
