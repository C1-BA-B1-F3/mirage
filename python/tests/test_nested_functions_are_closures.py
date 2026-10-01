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
import symtable
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "mirage"

# symtable gives every comprehension and lambda a scope of type "function"
# under one of these reserved names. They are expressions, not definitions,
# and the rule is about `def`.
SYNTHETIC = frozenset({"genexpr", "lambda", "listcomp", "setcomp", "dictcomp"})


def _defs_by_position(tree: ast.Module) -> dict[tuple[str, int], ast.AST]:
    found: dict[tuple[str, int], ast.AST] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            found[(node.name, node.lineno)] = node
    return found


def _binds_through_defaults(node: ast.AST, enclosing: frozenset[str]) -> bool:
    """Whether a def captures enclosing state through its parameter defaults.

    The loop-variable idiom (``def f(m, _n=n)``) binds the enclosing value
    at definition time instead of reading it at call time, which is the
    whole point when the def is created inside a loop. symtable sees no
    free variable, because by the time the body runs the name is a
    parameter -- but the closure is real and the capture is deliberate.

    Args:
        node: The nested function definition.
        enclosing: Names local to the function that contains it.

    Returns:
        True when a default expression reads an enclosing local.
    """
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    defaults = [
        *node.args.defaults,
        *[d for d in node.args.kw_defaults if d is not None]
    ]
    return any(
        isinstance(name, ast.Name) and name.id in enclosing
        for default in defaults for name in ast.walk(default))


def _offenders(path: Path, rel: str) -> list[str]:
    source = path.read_text()
    positions = _defs_by_position(ast.parse(source))
    found: list[str] = []

    def visit(table: symtable.SymbolTable, enclosing: frozenset[str] | None):
        for child in table.get_children():
            is_def = (child.get_type() == "function"
                      and child.get_name() not in SYNTHETIC)
            if is_def and enclosing is not None and not child.get_frees():
                node = positions.get((child.get_name(), child.get_lineno()))
                if node is None or not _binds_through_defaults(
                        node, enclosing):
                    found.append(
                        f"{rel}:{child.get_lineno()} {child.get_name()}")
            locals_ = frozenset(child.get_locals()) if is_def else enclosing
            visit(child, locals_ if is_def else enclosing)

    visit(symtable.symtable(source, str(path), "exec"), None)
    return found


def test_nested_functions_capture_enclosing_state():
    """A nested def exists to close over its enclosing scope, or not at all.

    The flat rule -- never nest -- is one the architecture cannot keep:
    every op factory and the read-through cache are closure factories,
    and a decorator has nowhere else to put its wrapper. Forbidding the
    shape outright would mean 39 standing violations and a rule nobody
    could enforce.

    What the rule was reaching for is the nesting that buys nothing: a
    helper written inside a function although it reads only its own
    arguments. That one costs a rebuilt function object per call, hides a
    testable unit inside a scope no test can reach, and grows the body it
    sits in. Capture is the line between the two, and it is mechanical:
    either the def reads a name from the scope above it (or binds one
    through a parameter default), or it belongs at module level.
    """
    offenders = []
    for path in sorted(SOURCE.rglob("*.py")):
        offenders.extend(_offenders(path, path.relative_to(SOURCE).as_posix()))
    assert not offenders, (
        "these nested functions capture nothing from the scope around "
        "them, so nesting them only hides them -- move them to module "
        "level:\n" + "\n".join(offenders))
