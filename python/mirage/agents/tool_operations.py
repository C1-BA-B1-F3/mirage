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

import shlex
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from mirage.agents.file_version import FileVersionTracker, StaleMirageFileError
from mirage.agents.io_text import decode, io_to_str, replace_text
from mirage.context.session_context import (
    reset_current_session,
    set_current_session,
)
from mirage.io.types import IOResult
from mirage.utils.path import gnu_dirname
from mirage.workspace.workspace import Workspace

DEFAULT_READ_LIMIT = 2000


@dataclass(frozen=True, slots=True)
class ToolResult:
    """One tool's answer, before any framework's result shape.

    The two servers spell the failure flag differently -- MCP puts
    `isError` on the wire, the Claude Agent SDK takes `is_error` -- so
    the shared layer carries the fact and each server renders it.

    Args:
        text (str): The text handed back to the agent.
        is_error (bool): True when the call failed.
    """

    text: str
    is_error: bool = False


def _io_result(io: IOResult) -> ToolResult:
    return ToolResult(io_to_str(io), io.exit_code != 0)


def number_lines(text: str, offset: int, limit: int) -> str:
    """Render a slice of a file the way the read tool reports it.

    Splits on newlines only. `str.splitlines` would also break on
    \\v, \\f, \\x1c-\\x1e, \\x85 and the Unicode separators, which
    would number a file containing any of them differently from the
    TypeScript tool.

    Args:
        text (str): The decoded file content.
        offset (int): First line to show, zero-based.
        limit (int): Maximum number of lines to show.

    Returns:
        str: The numbered lines, joined.
    """
    if not text:
        lines: list[str] = []
    else:
        parts = text.split("\n")
        lines = [part + "\n" for part in parts[:-1]]
        if parts[-1]:
            lines.append(parts[-1])
    sliced = lines[offset : offset + limit]
    return "".join(
        f"{i + offset + 1:>6}\t{line}" for i, line in enumerate(sliced)
    )


async def ensure_parents(ws: Workspace, path: str) -> None:
    """Create the directories a new file needs, parents first.

    Args:
        ws (Workspace): The workspace to create them in.
        path (str): Virtual path of the file about to be written.
    """
    parent = gnu_dirname(path)
    if parent in ("/", "", "."):
        return
    if await ws.vfs.exists(parent):
        return
    await ensure_parents(ws, parent)
    try:
        await ws.vfs.mkdir(parent)
    except OSError:
        if not await ws.vfs.exists(parent):
            raise


class MirageToolOperations:
    """The agent tools, independent of any agent framework.

    Args:
        workspace (Workspace): The workspace the tools act on.
        stale_write_protection (bool): False lets an agent overwrite a
            file that changed since it read it.
        session_id (str | None): The session the tools act as, with its
            cwd, environment and mount grants; None is the workspace's
            default session.
    """

    def __init__(
        self,
        workspace: Workspace,
        stale_write_protection: bool = True,
        session_id: str | None = None,
    ) -> None:
        self._ws = workspace
        self._session_id = session_id
        self._versions = FileVersionTracker(workspace, stale_write_protection)

    @contextmanager
    def _as_session(self) -> Iterator[None]:
        if self._session_id is None:
            yield
            return
        token = set_current_session(self._ws.get_session(self._session_id))
        try:
            yield
        finally:
            reset_current_session(token)

    async def shell(self, command: str) -> ToolResult:
        """Run a command line in the session's shell.

        Args:
            command (str): The command line to run.

        Returns:
            ToolResult: The command's rendered output.
        """
        return _io_result(
            await self._ws.shell(command, session_id=self._session_id)
        )

    async def read(
        self, path: str, offset: int = 0, limit: int = DEFAULT_READ_LIMIT
    ) -> ToolResult:
        """Read a file as line-numbered text.

        Args:
            path (str): Virtual path.
            offset (int): First line to show, zero-based.
            limit (int): Maximum number of lines to show.

        Returns:
            ToolResult: The numbered lines, or the failure.
        """
        with self._as_session():
            try:
                data = await self._versions.read(path)
            except (OSError, ValueError) as exc:
                if not await self._ws.vfs.exists(path):
                    return ToolResult(f"Error: file '{path}' not found", True)
                return ToolResult(f"Error: {exc}", True)
            return ToolResult(number_lines(decode(data), offset, limit))

    async def write(self, path: str, content: str) -> ToolResult:
        """Create a file, refusing to clobber an existing one.

        Args:
            path (str): Virtual path.
            content (str): Text to write.

        Returns:
            ToolResult: The confirmation, or the failure.
        """
        with self._as_session():
            if await self._ws.vfs.exists(path):
                return ToolResult(f"Error: file '{path}' already exists", True)
            await ensure_parents(self._ws, path)
            await self._versions.write(path, content)
            return ToolResult(f"Written: {path}")

    async def edit(
        self,
        path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> ToolResult:
        """Replace a string in an existing file.

        Args:
            path (str): Virtual path.
            old_string (str): The text to find.
            new_string (str): The text to put in its place.
            replace_all (bool): True replaces every occurrence.

        Returns:
            ToolResult: The confirmation, or the failure.
        """
        with self._as_session():
            try:
                content = decode(await self._versions.read_for_edit(path))
            except StaleMirageFileError as exc:
                return ToolResult(f"Error: {exc}", True)
            except (OSError, ValueError) as exc:
                if not await self._ws.vfs.exists(path):
                    return ToolResult(f"Error: file '{path}' not found", True)
                return ToolResult(f"Error: {exc}", True)
            new_content, count = replace_text(
                content, old_string, new_string, replace_all
            )
            if count == 0:
                return ToolResult(
                    f"Error: string not found in file: '{old_string}'", True
                )
            if count > 1 and not replace_all:
                return ToolResult(
                    f"Error: string appears {count} times. Pass replace_all=true",
                    True,
                )
            try:
                await self._versions.write_edit(path, new_content)
            except StaleMirageFileError as exc:
                return ToolResult(f"Error: {exc}", True)
            occurrences = count if replace_all else 1
            return ToolResult(f"Edited: {path} ({occurrences} occurrence(s))")

    async def ls(self, path: str) -> ToolResult:
        """List a directory.

        Args:
            path (str): Virtual path.

        Returns:
            ToolResult: The listing, or the failure.
        """
        return _io_result(
            await self._ws.shell(
                f"ls {shlex.quote(path)}", session_id=self._session_id
            )
        )

    async def grep(self, pattern: str, path: str) -> ToolResult:
        """Search recursively for a pattern.

        Args:
            pattern (str): The regex to search for.
            path (str): Virtual path to search under.

        Returns:
            ToolResult: The matches.
        """
        io = await self._ws.shell(
            f"grep -rn {shlex.quote(pattern)} {shlex.quote(path)}",
            session_id=self._session_id,
        )
        # grep exits 1 for "no match", which is a normal empty answer,
        # and >1 for a real failure (bad regex, unreadable path). Only
        # the second is a tool error; reporting the first as one would
        # tell the agent its search broke every time nothing matched.
        return ToolResult(io_to_str(io), io.exit_code > 1)

    async def glob(self, pattern: str, path: str = "/") -> ToolResult:
        """Find files, not directories, whose name matches a pattern.

        Only the pattern's last path component is matched, as ``find
        -name`` matches it, so ``src/**/*.py`` finds every ``.py`` file
        under ``path``.

        Args:
            pattern (str): A file-name pattern such as ``*.py``.
            path (str): Directory to search under.

        Returns:
            ToolResult: One path per line, or the failure.
        """
        name = pattern.rsplit("/", 1)[-1]
        return _io_result(
            await self._ws.shell(
                f"find {shlex.quote(path)} -type f -name {shlex.quote(name)}",
                session_id=self._session_id,
            )
        )
