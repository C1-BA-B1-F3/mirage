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

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Piece:
    """One stretch of an expanded word.

    Attributes:
        text (str): the text, a glob character quoting made literal
            carrying its mark.
        split (bool): whether field splitting reads it, which is true
            only of text an unquoted expansion produced. Literal and
            quoted text never splits, and quoted text opens a field
            even when it is empty (``""``).
    """

    text: str
    split: bool = False


@dataclass(frozen=True, slots=True)
class FieldBreak:
    """The boundary between two elements of a splat (``$@``, ``$*``).

    Attributes:
        joiner (str): what the boundary reads as where no field
            splitting happens (an assignment, a ``case`` word): a space
            between ``$@`` elements, the first character of IFS between
            ``$*`` ones.
    """

    joiner: str


Chunk = Piece | FieldBreak
