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

import math
from datetime import datetime, timezone


def to_iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def now_iso() -> str:
    return to_iso_z(datetime.now(timezone.utc))


def ns_to_iso(ns: int) -> str:
    """Spell a host file time in UTC to the millisecond, as Node's stat does.

    Node renders a stat time as ``Date(Math.round(sec * 1e3 + nsec / 1e6))``;
    rounding the same double here keeps a disk mount's times byte-identical
    across hosts, and the fraction is what ``find -newer`` compares.

    Args:
        ns (int): unix epoch nanoseconds (``st_mtime_ns``).
    """
    sec, nsec = divmod(ns, 1_000_000_000)
    whole, ms = divmod(math.floor(sec * 1e3 + nsec / 1e6 + 0.5), 1000)
    stamp = datetime.fromtimestamp(whole, tz=timezone.utc)
    return f"{stamp:%Y-%m-%dT%H:%M:%S}.{ms:03d}Z"


def epoch_to_iso(seconds: float) -> str:
    """Convert unix epoch seconds to a second-precision UTC ISO-8601 string.

    Floored to whole seconds (matching the TypeScript ``Math.floor``) so
    the two converters produce byte-identical output for negative
    (pre-1970) fractional timestamps as well.

    Args:
        seconds (float): unix epoch seconds (sub-second part is dropped).
    """
    return to_iso_z(
        datetime.fromtimestamp(math.floor(seconds), tz=timezone.utc))


def iso_to_epoch(iso: str) -> int:
    """Convert an ISO-8601 string to whole unix epoch seconds.

    The inverse of epoch_to_iso; a naive stamp (no offset, e.g. a
    ``touch -t`` overlay time) is read as UTC so Python and TypeScript
    agree. Floored to whole seconds (matching the TypeScript
    ``Math.floor``) so a negative fractional epoch yields the same value
    in both languages.

    Args:
        iso (str): ISO-8601 timestamp, with or without a ``Z``/offset.
    """
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return math.floor(dt.timestamp())
