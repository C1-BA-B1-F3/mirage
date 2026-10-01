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

from dulwich.object_store import BaseObjectStore, iter_tree_contents
from dulwich.objects import ObjectID


def tree_entries(
    store: BaseObjectStore, tree: bytes | None
) -> dict[bytes, tuple[int, bytes]]:
    """Every blob a tree holds, keyed by repository-relative path.

    Args:
        store (BaseObjectStore): the object database.
        tree (bytes | None): the tree id, None for the empty tree a
            root commit diffs against.
    """
    if tree is None:
        return {}
    return {
        entry.path: (entry.mode, entry.sha)
        for entry in iter_tree_contents(store, ObjectID(tree))
    }
