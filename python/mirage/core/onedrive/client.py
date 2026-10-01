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

from functools import partial

from mirage.accessor.onedrive import OneDriveConfig
from mirage.core.msgraph.client import encoded_path, id_segment
from mirage.core.msgraph.config import graph_api
from mirage.core.msgraph.drive import DriveLoc


def drive_base(config: OneDriveConfig) -> str:
    """The drive this mount addresses, as a Graph URL prefix.

    Exactly one target may be named (``OneDriveConfig`` enforces it), so
    the arms are alternatives rather than a precedence chain. Naming none
    means the signed-in user's own drive, which is the only form that
    works under delegated auth with no extra identifiers.

    Each identifier is escaped as a single path segment. A guest user's
    UPN carries ``#EXT#``, and interpolated raw that ``#`` would open a
    URL fragment and send a truncated path.

    Args:
        config (OneDriveConfig): mount config.
    """
    api = graph_api(config)
    if config.drive_id:
        return f"{api}/drives/{id_segment(config.drive_id)}"
    if config.site_id:
        return f"{api}/sites/{id_segment(config.site_id)}/drive"
    if config.group_id:
        return f"{api}/groups/{id_segment(config.group_id)}/drive"
    if config.user_id:
        return f"{api}/users/{id_segment(config.user_id)}/drive"
    return f"{api}/me/drive"


def _full_path(config: OneDriveConfig, path: str) -> str:
    p = path.strip("/")
    prefix = (config.key_prefix or "").strip("/")
    if prefix and p:
        return f"{prefix}/{p}"
    return prefix or p


def full_item_url(config: OneDriveConfig, full: str, action: str = "") -> str:
    """Graph URL of a drive item by its path from the drive root.

    Unlike :func:`item_url`, ``full`` is not placed under the mount's
    ``key_prefix``: this is how the prefix folders themselves are reached.

    Args:
        config (OneDriveConfig): mount config.
        full (str): path from the drive root; empty for the root itself.
        action (str): a trailing Graph segment such as ``/children``.
    """
    base = drive_base(config)
    full = full.strip("/")
    if not full:
        return f"{base}/root{action}"
    stem = f"{base}/root:/{encoded_path(full)}"
    if action:
        return f"{stem}:{action}"
    return stem


def item_url(config: OneDriveConfig, path: str, action: str = "") -> str:
    return full_item_url(config, _full_path(config, path), action)


def drive_ref_path(config: OneDriveConfig, folder: str = "") -> str:
    """A ``parentReference`` path for a mount-relative folder.

    The ``key_prefix`` applies here exactly like :func:`item_url`, or
    copy and rename destinations land at the drive root.

    Args:
        config (OneDriveConfig): mount config.
        folder (str): mount-relative folder; empty for the mount root.
    """
    base = drive_base(config)[len(graph_api(config)) :]
    full = _full_path(config, folder)
    if full:
        return f"{base}/root:/{encoded_path(full)}"
    return f"{base}/root:"


def drive_loc(config: OneDriveConfig, path: str) -> DriveLoc:
    stripped = path.strip("/")
    return DriveLoc(
        drive="",
        path=stripped,
        virt=stripped,
        url=partial(item_url, config),
        ref=partial(drive_ref_path, config),
    )
