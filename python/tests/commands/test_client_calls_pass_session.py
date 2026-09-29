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

import ast
from pathlib import Path

MIRAGE = Path(__file__).resolve().parents[2] / "mirage"


def _session_takers() -> dict[tuple[str, str], int | None]:
    """Every client function that takes a session, with its position."""
    takers: dict[tuple[str, str], int | None] = {}
    for path in MIRAGE.glob("core/*/client.py"):
        module = ".".join(
            path.relative_to(MIRAGE.parent).with_suffix("").parts)
        for node in ast.parse(path.read_text()).body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            positional = [a.arg for a in node.args.args]
            keyword = [a.arg for a in node.args.kwonlyargs]
            if "session" in positional:
                takers[(module, node.name)] = positional.index("session")
            elif "session" in keyword:
                takers[(module, node.name)] = None
    return takers


def _unpooled_calls(path: Path, takers: dict[tuple[str, str],
                                             int | None]) -> list[str]:
    tree = ast.parse(path.read_text())
    names: dict[str, tuple[str, str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                if (node.module, alias.name) in takers:
                    names[alias.asname
                          or alias.name] = (node.module, alias.name)
    out = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in names):
            continue
        if any(k.arg in ("session", None) for k in node.keywords):
            continue
        position = takers[names[node.func.id]]
        if position is not None and len(node.args) > position:
            continue
        out.append(f"{path.relative_to(MIRAGE)}:{node.lineno} "
                   f"{node.func.id}")
    return out


def test_every_mount_command_passes_its_session_pool():
    """A client call with no session opens an aiohttp session of its own
    and closes it after one request (``core/api/client.py``), so a mount
    command that forgot ``session=accessor.pool`` paid a TLS handshake
    per call: ``trello board list`` did it once per workspace. Every
    mount command holds an accessor, so every client call it makes hands
    the pool over."""
    takers = _session_takers()
    unpooled = [
        call
        for path in sorted((MIRAGE / "commands" / "builtin").rglob("*.py"))
        for call in _unpooled_calls(path, takers)
    ]
    assert unpooled == []
