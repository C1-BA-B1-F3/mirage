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

import importlib
import pkgutil

import pytest

import mirage.commands.builtin

# Every backend that takes the window itself instead of leaving it to the
# generic read-and-slice fallback. Most push it down to the store (one
# ranged GET rather than the whole object); the ones that render their
# content or already hold it in memory take the window right after
# building the bytes, so a windowed read is answered the same way
# everywhere. Losing a name here is not a test failure anywhere else:
# the fallback keeps the backend correct while it silently starts
# reading whole objects again.
NATIVE_RANGE = {
    "box",
    "databricks_volume",
    "dev",
    "dify",
    "discord",
    "disk",
    "dropbox",
    "gdrive",
    "gridfs",
    "hf_buckets",
    "hf_hub",
    "nextcloud",
    "onedrive",
    "ram",
    "redis",
    "s3",
    "sharepoint",
    "slack",
    "ssh",
}


def _io_tables() -> dict[str, object]:
    """Every backend's ``CommandIO``, keyed by backend package name."""
    tables: dict[str, object] = {}
    for mod in pkgutil.iter_modules(mirage.commands.builtin.__path__):
        if not mod.ispkg:
            continue
        try:
            io = importlib.import_module(
                f"mirage.commands.builtin.{mod.name}.io"
            )
        except ImportError:
            continue
        table = getattr(io, "IO", None)
        if table is not None and hasattr(table, "read_range"):
            tables[mod.name] = table
    return tables


def test_native_range_roster_is_exactly_the_declared_set():
    tables = _io_tables()
    assert tables, "no backend IO tables were discovered"
    actual = {n for n, t in tables.items() if t.read_range is not None}
    assert actual == NATIVE_RANGE & set(tables)


@pytest.mark.parametrize("name", sorted(NATIVE_RANGE))
def test_declared_backends_expose_the_slot(name):
    tables = _io_tables()
    if name not in tables:
        pytest.skip(f"{name} has no importable IO table here")
    assert tables[name].read_range is not None
