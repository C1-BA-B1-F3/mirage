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

from collections.abc import Iterator

from mirage.io import IOResult
from mirage.shell.parse.constants import (
    BASH_KEYWORDS,
    CASE_TERMINATORS,
    SEPARATOR_TOKENS,
    STRUCTURAL_TOKENS,
)
from mirage.shell.parse.parse import parse
from mirage.shell.types import TSNodeLike


def find_unterminated_backtick(command: str) -> str | None:
    """Locate a backtick substitution that is never closed.

    tree-sitter happily parses ``echo `echo a`` as a complete command,
    so the region has to be scanned directly. Quoting follows the shell
    reader: single quotes protect a backtick, double quotes do not, and
    once inside a substitution only a backslash escapes, which is why
    ``"`echo '`'`"`` is an error in bash rather than a quoted backtick.

    Args:
        command (str): the raw command line.

    Returns:
        str | None: text from the unmatched backtick on, or None.
    """
    quote: str | None = None
    dollar_quote = False
    opened: int | None = None
    last_dollar = -2
    i = 0
    while i < len(command):
        ch = command[i]
        if quote == "'":
            # $'...' takes backslash escapes, so \' does not close it;
            # a plain '...' treats every backslash literally.
            if dollar_quote and ch == "\\":
                i += 2
                continue
            if ch == "'":
                quote = None
                dollar_quote = False
            i += 1
            continue
        if ch == "\\":
            i += 2
            continue
        if opened is not None:
            if ch == "`":
                opened = None
            i += 1
            continue
        if ch == "`":
            opened = i
        elif ch == "'" and quote is None:
            quote = "'"
            dollar_quote = last_dollar == i - 1
        elif ch == '"':
            quote = None if quote == '"' else '"'
        elif ch == "$":
            last_dollar = i
        i += 1
    return command[opened:] if opened is not None else None


def _is_structural_error(node: TSNodeLike) -> bool:
    """True if an ERROR node represents a real syntactic problem.

    A real syntax error contains a bash keyword, a bracket / quote
    token, a statement separator, or a named subtree the parser tried
    to recover. A separator inside an ERROR node has nothing to
    separate (``;s``, ``| s``, ``a ; ; b``, ``a &; b``), and GNU bash
    5.2 refuses every such line with ``syntax error near unexpected
    token``; an earlier reading that bash accepts ``& ;`` was wrong.
    """
    for child in node.children:
        if child.is_named:
            return True
        if child.type in BASH_KEYWORDS:
            return True
        if child.type in STRUCTURAL_TOKENS:
            return True
        if child.type in SEPARATOR_TOKENS:
            return True
    return False


def _stray_case_terminator(node: TSNodeLike) -> str | None:
    """The text of a ``;;`` / ``;&`` / ``;;&`` token outside a case item.

    The grammar takes them as ordinary statement separators, so
    ``true;;s`` parses cleanly and would run ``s``; bash refuses the
    line at the token.

    Args:
        node (TSNodeLike): root node from parse().
    """
    stack = [node]
    while stack:
        current = stack.pop()
        for child in current.children:
            if child.type in CASE_TERMINATORS and current.type != "case_item":
                text = child.text
                return text.decode(errors="replace") if text else child.type
            stack.append(child)
    return None


_BODY_OPENERS = ("do", "{", "then", "else")
_BODY_CLOSERS = ("done", "}", "fi", "elif", "else")


def _empty_compound(node: TSNodeLike) -> str | None:
    """The token closing a compound list that holds no command.

    bash requires a command in every ``do``, ``then``, ``else`` and brace
    body (5.2: ``for x in a; do done`` is a syntax error near ``done``);
    the grammar accepts an empty one, comments aside.

    Args:
        node (TSNodeLike): root node from parse().
    """
    stack = [node]
    while stack:
        current = stack.pop()
        stack.extend(current.children)
        if current.type not in (
            "do_group",
            "compound_statement",
            "if_statement",
        ):
            continue
        opened = False
        for kid in (
            token
            for child in current.children
            for token in (
                child.children
                if child.type in ("elif_clause", "else_clause")
                else [child]
            )
        ):
            if opened and kid.type in _BODY_CLOSERS:
                return (kid.text or b"").decode(errors="replace")
            if kid.type in _BODY_OPENERS:
                opened = True
            elif kid.is_named and kid.type != "comment":
                opened = False
    return None


# Reserved words that close or continue a compound command; quoted,
# escaped, after an assignment or a redirect, or named as an alias the
# shell would expand there, they are plain words.
_RESERVED_CLOSERS = frozenset(
    {"do", "done", "elif", "else", "esac", "fi", "in", "then", "}", "]]"}
)


def _stray_reserved_word(
    node: TSNodeLike, aliases: frozenset[str]
) -> str | None:
    """The reserved word a command starts with, where none may stand.

    The grammar reads ``echo hi; fi`` as two commands and would run both;
    bash 5.2 refuses the line at ``fi``, as it does ``done``, ``then`` and
    the rest when they stand where a command starts.

    Args:
        node (TSNodeLike): root node from parse().
        aliases (frozenset[str]): alias names the shell would expand where
            a command starts, which bash tries before reserved words.
    """
    stack = [node]
    while stack:
        current = stack.pop()
        stack.extend(current.children)
        if current.type != "command" or not current.children:
            continue
        name = current.children[0]
        text = (name.text or b"").decode(errors="replace")
        if (
            name.type == "command_name"
            and text in _RESERVED_CLOSERS
            and text not in aliases
        ):
            return text
    return None


def _walk_named(node: TSNodeLike) -> Iterator[TSNodeLike]:
    yield node
    for child in node.named_children:
        yield from _walk_named(child)


def _is_recovered_quoted_heredoc_end(
    previous: TSNodeLike | None, error: TSNodeLike
) -> bool:
    if previous is None:
        return False
    error_text = (error.text or b"").decode().strip()
    if not error_text:
        return False
    for candidate in _walk_named(previous):
        if candidate.type != "heredoc_redirect":
            continue
        start = None
        end = None
        for child in candidate.named_children:
            if child.type == "heredoc_start":
                start = (child.text or b"").decode()
            elif child.type == "heredoc_end":
                end = (child.text or b"").decode()
        if (
            start is not None
            and ("'" in start or '"' in start)
            and not end
            and start.replace("'", "").replace('"', "") == error_text
        ):
            return True
    return False


def _missing_quote(node: TSNodeLike) -> str | None:
    stack = [node]
    while stack:
        current = stack.pop()
        if current.is_missing and current.type in ("'", '"', "`"):
            return ""
        stack.extend(current.children)
    return None


def find_syntax_error(
    node: TSNodeLike, aliases: frozenset[str] = frozenset()
) -> str | None:
    """Locate structural errors and missing tokens throughout a parsed AST.

    Args:
        node (TSNodeLike): root node from parse().
        aliases (frozenset[str]): alias names the shell would expand where
            a command starts; a reserved word among them is a command.

    Returns:
        str | None: text of the offending region, or None if the AST is clean.
    """
    # Parameter syntax is judged during expansion (bad substitution), and
    # `[` is a builtin whose argument grammar is judged by that builtin.
    if node.type == "expansion":
        return (
            ""
            if any(c.is_missing and c.type == "}" for c in node.children)
            else None
        )
    if (
        node.type == "test_command"
        and node.children
        and node.children[0].type == "["
    ):
        return _missing_quote(node)
    if node.type == "command_substitution":
        source = (node.text or b"").decode()
        unclosed = find_unterminated_backtick(source)
        if unclosed is not None:
            return unclosed
        if source.startswith("$(") and source.endswith(")"):
            return find_syntax_error(parse(source[2:-1]), aliases)
    stray = _stray_case_terminator(node)
    if stray is not None:
        return stray
    empty = _empty_compound(node)
    if empty is not None:
        return empty
    reserved = _stray_reserved_word(node, aliases)
    if reserved is not None:
        return reserved
    if not node.has_error:
        return find_unterminated_quote(node)
    previous = None
    for child in node.children:
        # Bash permits unquoted spaces in associative subscripts. The
        # grammar recovers their earlier plain words as ERROR children.
        if (
            node.type == "subscript"
            and child.type == "ERROR"
            and child.children
            and all(
                part.type == "word" and not part.has_error
                for part in child.children
            )
        ):
            continue
        if child.is_missing:
            text = child.text
            return text.decode(errors="replace") if text else ""
        if (
            child.type == "ERROR"
            and _is_structural_error(child)
            and not (
                node.type == "for_statement"
                and (child.text or b"").strip() == b"in"
            )
        ):
            if _is_recovered_quoted_heredoc_end(previous, child):
                previous = child
                continue
            text = child.text
            return text.decode(errors="replace") if text else ""
        if child.type != "ERROR":
            nested = find_syntax_error(child, aliases)
            if nested is not None:
                return nested
        if child.is_named:
            previous = child
    return None


def find_unterminated_quote(node: TSNodeLike) -> str | None:
    """Find a missing quote in the parser's erroneous regions.

    Complete strings, comments and heredoc bodies remain opaque. The
    grammar represents an open double quote as a missing token or an
    ERROR child, and an open single quote as a leaf ERROR span. An ANSI-C
    string ending in an escaped quote can parse cleanly, so check its
    closing delimiter as well.

    Args:
        node (TSNodeLike): the parsed command being refused.
    """
    if node.is_missing and node.type in ("'", '"'):
        return node.type
    if node.type == "ansi_c_string":
        source = (node.text or b"").decode()
        before = source[:-1]
        if (len(before) - len(before.rstrip("\\"))) % 2:
            return "'"
        return None
    for child in node.children:
        quote = find_unterminated_quote(child)
        if quote is not None:
            return quote
    if node.type == "ERROR":
        if not node.children and (node.text or b"").startswith(b"'"):
            return "'"
        if sum(child.type == '"' for child in node.children) % 2:
            return '"'
    return None


def syntax_error_result(
    offending: str, node: TSNodeLike | None = None
) -> IOResult:
    """Exit 2 with the bash-style diagnostic for an unparsable line.

    Args:
        offending (str): the span the parser flagged.
        node (TSNodeLike | None): the parsed command, for quote diagnostics.
    """
    quote = find_unterminated_quote(node) if node is not None else None
    if quote is not None:
        return IOResult(
            exit_code=2,
            stderr=(
                "mirage: unexpected EOF while looking for matching "
                f"`{quote}'\n"
            ).encode(),
        )
    snippet = offending.strip()
    err = (
        f"mirage: syntax error near {snippet!r}\n".encode()
        if snippet
        else b"mirage: syntax error in command\n"
    )
    return IOResult(exit_code=2, stderr=err)
