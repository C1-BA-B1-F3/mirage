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
from contextlib import contextmanager
from pathlib import PurePosixPath
from stat import S_ISREG
from typing import Any

from mirage.errors import FsCondition, classify
from mirage.runtime.handles import parse_mode
from mirage.runtime.open import apply_open
from mirage.runtime.python.monty.binding import (
    MontyFileHandle,
    OSAccess,
    StatResult,
    path_from_arg,
)
from mirage.runtime.python.monty.constants import (
    MAX_URANDOM_BYTES,
    NOT_A_LINK,
)
from mirage.runtime.python.monty.errors import guest_error
from mirage.runtime.python.monty.list import merge_entries
from mirage.runtime.python.monty.stat import stat_result
from mirage.runtime.types import VFSEntry, VFSStat
from mirage.runtime.vfs import RuntimeVFS


@contextmanager
def _as_guest(path: str, target: str | None = None) -> Iterator[None]:
    """Re-raise a mount failure the way guest CPython raises it.

    A backend words its refusals its own way; a guest catches the
    builtin and may print its message. Every named condition converts,
    so a non-empty rmdir is ``OSError`` errno 39 wherever it happened,
    and a failure the vocabulary does not name passes through as is.

    Args:
        path (str): the path the operation names.
        target (str | None): a rename's destination.
    """
    try:
        yield
    except Exception as exc:
        condition = classify(exc)
        if condition is None:
            raise
        raise guest_error(condition, path, target) from exc


class MirageOSAccess(OSAccess):
    """Monty's OS door: a mounted path is the workspace's, any other scratch.

    This is monty's tier of the interception taxonomy: the binding hands
    the interpreter a host OS object and calls its methods, so mirage
    subclasses that object rather than hooking a syscall layer. Every
    call routes on the path. One a mount serves is answered by the
    file door alone, with the mount's own rows and CPython's wording
    for its refusals. Any other path is guest scratch space, served by
    the binding's own in-memory tree, which is also where the
    environment, the clocks and ``urandom`` come from. The TypeScript
    twin routes the same way over its ``ScratchTree``.

    Monty hands the door whole-file calls: an open, then reads of the
    whole file and appends of each new write. So an open applies its
    mode's effect on the mount (``apply_open``) and nothing else,
    and each write after it ships only its own bytes.

    The bridge uses synchronous callbacks, so the core's hop parks the
    tokio worker for the whole I/O wait. That caps concurrent
    I/O-waiting runs at Monty's worker pool size, which is the core
    count by default; TOKIO_WORKER_THREADS raises it, and parked
    workers cost stack pages, not CPU (measured: 100 concurrent 1s-I/O
    runs finish in ~2s at 64 workers versus ~8s at 14).

    Args:
        core (RuntimeVFS | None): the execution's file door, built with
            ``RuntimeVFS.of(context)``; None outside a workspace.
        environ (dict[str, str]): the guest's environment.
    """

    def __init__(
        self, core: RuntimeVFS | None, environ: dict[str, str]
    ) -> None:
        super().__init__(
            [], environ=dict(environ), max_urandom_bytes=MAX_URANDOM_BYTES
        )
        self._core = core

    def _door(self, path: PurePosixPath) -> RuntimeVFS | None:
        """The file door when a mount serves `path`, None for scratch.

        Args:
            path (PurePosixPath): the guest path.
        """
        core = self._core
        if core is None or not core.serves(str(path)):
            return None
        return core

    def _row(self, door: RuntimeVFS, path: PurePosixPath) -> VFSStat | None:
        with _as_guest(str(path)):
            return door.stat_or_none(str(path))

    def _listing(self, path: PurePosixPath) -> list[VFSEntry] | None:
        """What the workspace lists at `path`, served or not.

        A directory the workspace lists but no mount claims (the root
        above nested mounts, `/parent` when only `/parent/child` is
        mounted) has no row anywhere, and a mount may serve a listing
        for a directory it has no row for, so the predicates fall back
        to this on both routes.

        Args:
            path (PurePosixPath): the guest path.
        """
        if self._core is None:
            return None
        with _as_guest(str(path)):
            return self._core.listing_or_none(str(path))

    def _scratch_parent(self, path: PurePosixPath) -> None:
        """Make a scratch path's parent a tree directory when only the
        workspace has it.

        A directory the workspace lists but no mount claims (the root
        above nested mounts) is one the guest sees as a directory, so a
        scratch file may be created in it like in any other; the tree
        holds it from then on, and its listing merges both.

        Args:
            path (PurePosixPath): the scratch path about to be created.
        """
        parent = path.parent
        if super().path_exists(parent) or self._listing(parent) is None:
            return
        super().path_mkdir(parent, True, True)

    def path_exists(self, path: PurePosixPath) -> bool:
        door = self._door(path)
        if door is not None:
            if self._row(door, path) is not None:
                return True
        elif super().path_exists(path):
            return True
        return self._listing(path) is not None

    def path_is_file(self, path: PurePosixPath) -> bool:
        door = self._door(path)
        if door is None:
            return bool(super().path_is_file(path))
        row = self._row(door, path)
        return row is not None and S_ISREG(row.mode)

    def path_is_dir(self, path: PurePosixPath) -> bool:
        door = self._door(path)
        if door is not None:
            row = self._row(door, path)
            if row is not None:
                return row.is_dir
        elif super().path_is_dir(path):
            return True
        return self._listing(path) is not None

    def path_is_symlink(self, path: PurePosixPath) -> bool:
        """Whether the name plane holds a symlink at `path`.

        Asked through readlink, on either route: monty's tree holds no
        links, and the name plane may hold one at an unmounted path.
        Creation stays out of reach, because the binding has no symlink
        verb to override.

        Args:
            path (PurePosixPath): the guest path to test.
        """
        if self._core is None:
            return False
        with _as_guest(str(path)):
            try:
                self._core.readlink(str(path))
            except Exception as caught:
                if classify(caught) not in NOT_A_LINK:
                    raise
                return False
        return True

    def path_stat(self, path: PurePosixPath) -> Any:
        """The path's stat: the mount's own row whenever it has one.

        A mounted file's mode and mtime are the mount's, so a chmod the
        shell made shows. A path with no row is monty's own, or a
        directory the workspace only implies, which stats as monty's
        default directory.

        Args:
            path (PurePosixPath): the guest path to stat.
        """
        door = self._door(path)
        row = self._row(door, path) if door is not None else None
        if row is not None:
            return stat_result(row)
        if super().path_exists(path) or self._listing(path) is None:
            return super().path_stat(path)
        return StatResult.dir_stat()

    def path_iterdir(self, path: PurePosixPath) -> list[PurePosixPath]:
        """List a directory, folding the workspace's names into scratch.

        `iterdir('/')` must show the mount roots beside the guest's own
        scratch entries, so an unmounted directory merges the two.

        Args:
            path (PurePosixPath): the directory to list.
        """
        door = self._door(path)
        if door is not None:
            with _as_guest(str(path)):
                entries = door.readdir(str(path), classify=False)
            return merge_entries(path, [], [entry.path for entry in entries])
        listed = self._listing(path)
        if listed is None:
            return super().path_iterdir(path)
        local = super().path_iterdir(path) if super().path_is_dir(path) else []
        return merge_entries(path, local, [entry.path for entry in listed])

    def path_open(self, path: PurePosixPath, mode: str) -> MontyFileHandle:
        door = self._door(path)
        if door is None:
            if MontyFileHandle(str(path), mode).writable:
                self._scratch_parent(path)
            return super().path_open(path, mode)
        # Built first, as monty's own tree does: a malformed mode must
        # raise before any effect lands on the mount.
        handle = MontyFileHandle(str(path), mode)
        with _as_guest(str(path)):
            apply_open(door, str(path), parse_mode(mode))
        return handle

    def path_read_text(self, path: PurePosixPath | MontyFileHandle) -> str:
        if self._door(path_from_arg(path)) is None:
            return str(super().path_read_text(path))
        return self.path_read_bytes(path).decode()

    def path_read_bytes(self, path: PurePosixPath | MontyFileHandle) -> bytes:
        target = path_from_arg(path)
        door = self._door(target)
        if door is None:
            return bytes(super().path_read_bytes(path))
        with _as_guest(str(target)):
            return door.read(str(target))

    def path_write_text(
        self, path: PurePosixPath | MontyFileHandle, data: str
    ) -> int:
        if self._door(path_from_arg(path)) is None:
            self._scratch_parent(path_from_arg(path))
            return int(super().path_write_text(path, data))
        self.path_write_bytes(path, data.encode())
        return len(data)

    def path_write_bytes(
        self, path: PurePosixPath | MontyFileHandle, data: bytes
    ) -> int:
        target = path_from_arg(path)
        door = self._door(target)
        if door is None:
            self._scratch_parent(target)
            return int(super().path_write_bytes(path, data))
        with _as_guest(str(target)):
            door.write(str(target), bytes(data))
        return len(data)

    def path_append_text(
        self, path: PurePosixPath | MontyFileHandle, data: str
    ) -> int:
        if self._door(path_from_arg(path)) is None:
            self._scratch_parent(path_from_arg(path))
            return int(super().path_append_text(path, data))
        self.path_append_bytes(path, data.encode())
        return len(data)

    def path_append_bytes(
        self, path: PurePosixPath | MontyFileHandle, data: bytes
    ) -> int:
        """Send only the appended bytes; monty hands an append nothing else.

        Re-sending everything written so far turns a write loop
        quadratic, so a mount with its own append op carries just these
        bytes, and the door falls back to a whole-file write only for
        the mount without one.

        Args:
            path (PurePosixPath | MontyFileHandle): the file.
            data (bytes): only the newly appended bytes.
        """
        target = path_from_arg(path)
        door = self._door(target)
        if door is None:
            self._scratch_parent(target)
            return int(super().path_append_bytes(path, data))
        with _as_guest(str(target)):
            door.append(str(target), bytes(data))
        return len(data)

    def path_mkdir(
        self, path: PurePosixPath, parents: bool, exist_ok: bool
    ) -> None:
        """Create a directory on the mount, keeping pathlib's flags.

        `parents` rides through to the backend op, which takes it;
        `exist_ok` is answered here, since the op has no such argument
        and backends differ on whether creating an existing directory
        raises at all. It forgives an existing directory only: a file
        at the target still raises, pathlib's own rule.

        Args:
            path (PurePosixPath): the directory to create.
            parents (bool): create missing ancestors too.
            exist_ok (bool): stay quiet when it already exists.
        """
        door = self._door(path)
        if door is None:
            self._scratch_parent(path)
            super().path_mkdir(path, parents, exist_ok)
            return
        row = self._row(door, path)
        if row is not None and not row.is_dir:
            raise guest_error(FsCondition.EEXIST, str(path))
        if row is not None or self._listing(path) is not None:
            if exist_ok:
                return
            raise guest_error(FsCondition.EEXIST, str(path))
        with _as_guest(str(path)):
            door.mkdir(str(path), parents=parents)

    def path_rmdir(self, path: PurePosixPath) -> None:
        door = self._door(path)
        if door is None:
            super().path_rmdir(path)
            return
        with _as_guest(str(path)):
            door.rmdir(str(path))

    def path_unlink(self, path: PurePosixPath) -> None:
        door = self._door(path)
        if door is None:
            super().path_unlink(path)
            return
        with _as_guest(str(path)):
            door.unlink(str(path))

    def path_rename(self, path: PurePosixPath, target: PurePosixPath) -> None:
        """Rename within one mount or within scratch, never across.

        The dispatcher picks the mount from the source alone and hands
        the destination to that same backend, which reads it against
        its own keyspace, so a rename between two mounts, or between a
        mount and scratch, is refused with EXDEV, POSIX's answer for a
        rename across filesystems. Monty ships no `shutil`, so guest
        code writes the copy-and-delete fallback by hand, and the errno
        is what tells it to.

        Args:
            path (PurePosixPath): the source path.
            target (PurePosixPath): the destination path.

        Raises:
            OSError: EXDEV when the two ends live apart.
        """
        door = self._door(path)
        if (door is None) != (self._door(target) is None):
            raise guest_error(FsCondition.CROSS_MOUNT, str(path), str(target))
        if door is None:
            self._scratch_parent(target)
            super().path_rename(path, target)
            self._restamp(target)
            return
        with _as_guest(str(path), str(target)):
            door.rename(str(path), str(target))

    def _restamp(self, target: PurePosixPath) -> None:
        """Re-point a renamed scratch file at the name it now has.

        monty's `path_rename` moves a file between directory dicts
        without updating the file's own `path`/`name`, which it does do
        for the directory branch (`_update_paths_recursive`).
        `path_unlink` then deletes by `file.name`, so renaming a.txt to
        b.txt and removing b.txt raises `KeyError: 'a.txt'`, which is
        not an OSError and so cannot be caught by guest code.
        Reproduces on a bare `OSAccess` with no mirage in the picture,
        so it belongs upstream; drop this once a release carries the
        fix.

        Args:
            target (PurePosixPath): the path the file now has.
        """
        entry = self._get_entry(target)
        if entry is None or isinstance(entry, dict):
            return
        entry.path = target
        entry.name = target.name
