import re
from dataclasses import replace
from typing import Any, cast

import tree_sitter

from mirage.shell.parse.heredoc.types import HeredocSource

PREFIX = re.compile(rb"time(?=[ \t\r\n;|&)]|$)[ \t]*"
                    rb"(?:(-p)(?=[ \t\r\n;|&)]|$)[ \t]*)?"
                    rb"(?:--(?=[ \t\r\n;|&)]|$)[ \t]*)?")
STATEMENTS = frozenset({
    "command", "test_command", "arithmetic_expansion", "pipeline",
    "redirected_statement", "negated_command", "subshell",
    "compound_statement", "if_statement", "for_statement", "while_statement",
    "case_statement"
})


def lower_timing(
    parser: tree_sitter.Parser, source: HeredocSource
) -> tuple[HeredocSource, list[tuple[int, bool, int, int]]]:
    """Remove reserved prefixes before parsing their pipeline/compound body.

    Args:
        parser (tree_sitter.Parser): Bash parser used for command positions.
        source (HeredocSource): source map after gathering input documents.
    """
    data = source.source
    marks: list[tuple[int, bool, int, int]] = []
    while True:
        root = parser.parse(data).root_node
        stack = [root]
        edits: list[tuple[int, int, bytes]] = []
        while stack:
            node = stack.pop()
            stack.extend(node.children)
            if node.type != "command" or not node.children:
                continue
            name = node.child_by_field_name("name")
            if name is None or name.text != b"time" or node.children[
                    0].id != name.id:
                continue
            parent = node.parent
            if (parent is not None and parent.type == "pipeline"
                    and parent.named_children[0].id != node.id):
                continue
            match = PREFIX.match(data, name.start_byte)
            if match is None:
                continue
            end = match.end()
            while end < len(data) and data[end] in b" \t":
                end += 1
            empty = end == len(data) or data[end] in b"\n;&)"
            replacement = b" " * (end - name.start_byte)
            anchor = end
            if empty:
                replacement = b":" + replacement[1:]
                anchor = name.start_byte
            marks = [(source.offsets[anchor] if position
                      == source.offsets[name.start_byte] else position, flag,
                      begin, finish)
                     for position, flag, begin, finish in marks]
            marks.append(
                (source.offsets[anchor], match.group(1) is not None,
                 source.offsets[name.start_byte], source.offsets[end]))
            edits.append((name.start_byte, end, replacement))
        if not edits:
            break
        for start, end, replacement in sorted(edits, reverse=True):
            data = data[:start] + replacement + data[end:]
    return replace(source, source=data), marks


class TimingNode:
    """Preserve native node behavior while adding an execution-only wrapper."""

    def __init__(self,
                 node: Any,
                 targets: dict[int, tuple[bool, ...]],
                 source: HeredocSource,
                 spans: list[tuple[int, int]],
                 skip: bool = False):
        self._node = node
        self._targets = targets
        self._source = source
        self._spans = spans
        self.timing = () if skip else targets.get(node.id, ())

    def __getattr__(self, name: str) -> Any:
        return getattr(self._node, name)

    @property
    def type(self) -> str:
        return "timed_statement" if self.timing else self._node.type

    def _wrap(self, node: Any) -> Any:
        return None if node is None else TimingNode(node, self._targets,
                                                    self._source, self._spans)

    @property
    def children(self) -> list[Any]:
        if self.timing:
            return [
                TimingNode(self._node, self._targets, self._source,
                           self._spans, True)
            ]
        return [self._wrap(node) for node in self._node.children]

    @property
    def named_children(self) -> list[Any]:
        return self.children if self.timing else [
            self._wrap(node) for node in self._node.named_children
        ]

    @property
    def parent(self) -> Any:
        return self._wrap(self._node.parent)

    @property
    def prev_sibling(self) -> Any:
        return self._wrap(self._node.prev_sibling)

    @property
    def next_sibling(self) -> Any:
        return self._wrap(self._node.next_sibling)

    @property
    def source_text(self) -> bytes:
        if any(self.start_byte <= start < self.end_byte
               for start, _ in self._source.documents):
            return cast(bytes, self._node.source_text)
        text = bytearray(self._node.text or b"")
        for index, offset in enumerate(
                self._source.offsets[self.start_byte:self.end_byte]):
            if any(start <= offset < end for start, end in self._spans):
                text[index] = self._source.original[offset]
        return bytes(text)

    def child_by_field_name(self, name: str) -> Any:
        return self._wrap(self._node.child_by_field_name(name))


def wrap_timing(root: Any, source: HeredocSource,
                marks: list[tuple[int, bool, int, int]]) -> TimingNode:
    """Attach each prefix to the entire following pipeline, within its list.

    Args:
        root (Any): mapped parse tree.
        source (HeredocSource): final source positions.
        marks (list[tuple[int, bool, int, int]]): body starts and -p choices.
    """
    targets: dict[int, tuple[bool, ...]] = {}
    for position, portable, _, _ in marks:
        stack = [root]
        while stack:
            node = stack.pop()
            if node.type in STATEMENTS and source.offsets[
                    node.start_byte] == position:
                targets[node.id] = (portable or any(targets.get(node.id,
                                                                ())), )
                break
            stack.extend(reversed(node.named_children))
    return TimingNode(root, targets, source,
                      [(start, end) for _, _, start, end in marks])
