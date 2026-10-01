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

from mirage.types import PathSpec
from mirage.workspace.executor.builtins.condition.constants import (
    BINARY_OPS,
    UNARY_OPS,
)
from mirage.workspace.executor.builtins.condition.operators import (
    apply_binary,
    apply_unary,
)
from mirage.workspace.executor.builtins.condition.types import (
    CondContext,
    CondError,
)
from mirage.workspace.executor.builtins.scope import _scope_path


async def _eval_one(ctx: CondContext, arg: str | PathSpec) -> bool:
    """One-argument rule: true when the operand is non-empty.

    Args:
        ctx (CondContext): evaluation context.
        arg (str | PathSpec): sole operand.
    """
    return _scope_path(arg) != ""


async def _eval_two(ctx: CondContext, argv: list[str | PathSpec]) -> bool:
    """Two-argument rule: ``!`` or a unary operator.

    Args:
        ctx (CondContext): evaluation context.
        argv (list[str | PathSpec]): exactly two operands.
    """
    first = _scope_path(argv[0])
    if first == "!":
        return not await _eval_one(ctx, argv[1])
    if first in UNARY_OPS:
        return await apply_unary(ctx, first, argv[1])
    raise CondError(f"{ctx.name}: {first}: unary operator expected")


async def _eval_three(ctx: CondContext, argv: list[str | PathSpec]) -> bool:
    """Three-argument rule: binary op, ``-a``/``-o``, ``!``, or parens.

    Args:
        ctx (CondContext): evaluation context.
        argv (list[str | PathSpec]): exactly three operands.
    """
    mid = _scope_path(argv[1])
    if mid == "-a":
        return await _eval_one(ctx, argv[0]) and await _eval_one(ctx, argv[2])
    if mid == "-o":
        return await _eval_one(ctx, argv[0]) or await _eval_one(ctx, argv[2])
    if mid in BINARY_OPS:
        return await apply_binary(ctx, argv[0], mid, argv[2])
    first = _scope_path(argv[0])
    if first == "!":
        return not await _eval_two(ctx, argv[1:])
    if first == "(" and _scope_path(argv[2]) == ")":
        return await _eval_one(ctx, argv[1])
    raise CondError(f"{ctx.name}: {mid}: binary operator expected")


async def _eval_four(ctx: CondContext, argv: list[str | PathSpec]) -> bool:
    """Four-argument rule: leading ``!`` or parens, else expr parser.

    Args:
        ctx (CondContext): evaluation context.
        argv (list[str | PathSpec]): exactly four operands.
    """
    first = _scope_path(argv[0])
    if first == "!":
        return not await _eval_three(ctx, argv[1:])
    if first == "(" and _scope_path(argv[3]) == ")":
        return await _eval_two(ctx, argv[1:3])
    parser = _ExprParser(ctx, argv)
    return await parser.run()


class _ExprParser:
    """Recursive-descent ``test`` expression parser (>4 args, GNU expr
    grammar: or -> and -> term with ``!`` and parentheses)."""

    def __init__(self, ctx: CondContext, argv: list[str | PathSpec]) -> None:
        self.ctx = ctx
        self.argv = argv
        self.pos = 0

    def _peek(self, offset: int = 0) -> str | None:
        i = self.pos + offset
        if i < len(self.argv):
            return _scope_path(self.argv[i])
        return None

    async def run(self) -> bool:
        result = await self._or_expr()
        if self.pos != len(self.argv):
            raise CondError(f"{self.ctx.name}: too many arguments")
        return result

    async def _or_expr(self) -> bool:
        result = await self._and_expr()
        while self._peek() == "-o":
            self.pos += 1
            right = await self._and_expr()
            result = result or right
        return result

    async def _and_expr(self) -> bool:
        result = await self._term()
        while self._peek() == "-a":
            self.pos += 1
            right = await self._term()
            result = result and right
        return result

    async def _term(self) -> bool:
        tok = self._peek()
        if tok is None:
            raise CondError(f"{self.ctx.name}: argument expected")
        if tok == "!":
            self.pos += 1
            return not await self._term()
        if tok == "(":
            self.pos += 1
            result = await self._or_expr()
            if self._peek() != ")":
                raise CondError(f"{self.ctx.name}: `)' expected")
            self.pos += 1
            return result
        nxt = self._peek(1)
        if nxt in BINARY_OPS and self._peek(2) is not None:
            left = self.argv[self.pos]
            right = self.argv[self.pos + 2]
            self.pos += 3
            return await apply_binary(self.ctx, left, nxt, right)
        if tok in UNARY_OPS and nxt is not None and nxt not in ("-a", "-o"):
            operand = self.argv[self.pos + 1]
            self.pos += 2
            return await apply_unary(self.ctx, tok, operand)
        self.pos += 1
        return tok != ""


async def eval_flat(ctx: CondContext, argv: list[str | PathSpec]) -> bool:
    """Evaluate a flat ``test``/``[`` argument list with bash's arity
    rules.

    Args:
        ctx (CondContext): evaluation context.
        argv (list[str | PathSpec]): operands, brackets excluded.
    """
    n = len(argv)
    if n == 0:
        return False
    if n == 1:
        return await _eval_one(ctx, argv[0])
    if n == 2:
        return await _eval_two(ctx, argv)
    if n == 3:
        return await _eval_three(ctx, argv)
    if n == 4:
        return await _eval_four(ctx, argv)
    parser = _ExprParser(ctx, argv)
    return await parser.run()
