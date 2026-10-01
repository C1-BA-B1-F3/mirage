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

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal, TypeAlias, TypeVar

from mirage.accessor.base import Accessor
from mirage.cache.index import IndexEntry

A = TypeVar("A", bound=Accessor)

DirRows: TypeAlias = dict[str, list[tuple[str, IndexEntry]]]

LoadRows: TypeAlias = Callable[[A, str], Awaitable[DirRows]]


@dataclass(frozen=True)
class ResolvedDirectory:
    virtual_key: str
    mount_prefix: str
    is_dir: Literal[True] = True
    children: list[str] | None = None


@dataclass(frozen=True)
class ResolvedFile:
    virtual_key: str
    mount_prefix: str
    entry: IndexEntry
    is_dir: Literal[False] = False


ResolvedPath: TypeAlias = ResolvedDirectory | ResolvedFile
