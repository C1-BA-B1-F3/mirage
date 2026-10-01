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

from mirage.core.msgraph.client import encoded_path, id_segment
from mirage.core.msgraph.config import MsGraphConfig, graph_api


def item_url(
    config: MsGraphConfig, drive_id: str, path: str, action: str = ""
) -> str:
    """A drive item's Graph URL.

    Takes the config, not just the drive id, because the service root is
    a per-mount setting (national cloud, private endpoint, test server)
    rather than a constant.

    Args:
        config (MsGraphConfig): mount config carrying the service root.
        drive_id (str): drive holding the item.
        path (str): drive-relative item path.
        action (str): optional trailing Graph action, e.g. ``/content``.
    """
    base = f"{graph_api(config)}/drives/{id_segment(drive_id)}"
    p = path.strip("/")
    if not p:
        return f"{base}/root{action}"
    stem = f"{base}/root:/{encoded_path(p)}"
    if action:
        return f"{stem}:{action}"
    return stem


def drive_ref_path(drive_id: str, folder: str = "") -> str:
    base = f"/drives/{drive_id}"
    stripped = folder.strip("/")
    if stripped:
        return f"{base}/root:/{encoded_path(stripped)}"
    return f"{base}/root:"
