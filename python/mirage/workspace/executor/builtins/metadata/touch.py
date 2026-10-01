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

from collections.abc import AsyncIterator
from functools import partial

from mirage.commands.builtin.utils.paths import (
    dispatch_stat,
    dot_refusal,
    typed_spec,
)
from mirage.context import DEFAULT_UMASK
from mirage.io import IOResult
from mirage.runtime.types import DispatchFn
from mirage.types import FileType, PathSpec
from mirage.utils.errors import (
    FS_ERRORS,
    OperationNotSupportedError,
    fs_strerror,
    walk_refusal,
)
from mirage.workspace.executor.builtins.metadata.metadata import (
    apply_link_attrs,
    follow_operand,
    now_iso,
    parse_touch_stamp,
    permission_error,
    setattr_via,
)
from mirage.workspace.executor.builtins.shared import (
    expand_operands,
    fail,
    finish,
    split_value_flags,
)
from mirage.workspace.executor.builtins.types import Result
from mirage.workspace.mount.namespace import Namespace
from mirage.workspace.session import SessionState


async def handle_touch(
    namespace: Namespace,
    dispatch: DispatchFn,
    session: SessionState,
    args: list[str | PathSpec],
) -> Result:
    """touch: set access/modification times, creating missing files.

    GNU flags: -a/-m select which times, -c no-create, -h no-dereference
    (writes the link node's own mtime), -t STAMP / -d STRING supply the
    time, -r FILE copies times from a reference file.

    Args:
        namespace (Namespace): addressing authority.
        dispatch (DispatchFn): op dispatcher.
        session (SessionState): session whose cwd resolves relative -r paths.
        args (list[str | PathSpec]): args after the command name.
    """
    flags, values, operands, bad = split_value_flags(args, "acmh", "tdr")
    if bad is not None:
        return fail("touch", f"touch: invalid option -- '{bad}'\n", 2)
    if not operands:
        return fail("touch", "touch: missing file operand\n", 1)

    try:
        stamp = parse_touch_stamp(values.get("t"), values.get("d"))
    except ValueError as exc:
        return fail("touch", f"touch: invalid date format '{exc}'\n", 1)
    if stamp is None and "r" in values:
        # The spelling as typed, so the empty name is refused rather than
        # read as the working directory.
        ref = typed_spec(values["r"], session.cwd)
        try:
            ref_stat, _ = await dispatch("stat", ref)
        except FS_ERRORS as exc:
            return fail(
                "touch",
                f"touch: failed to get attributes of "
                f"'{values['r']}': {fs_strerror(exc)}\n",
            )
        stamp = ref_stat.modified
    if stamp is None:
        stamp = now_iso()

    atime = stamp if "a" in flags or "m" not in flags else None
    mtime = stamp if "m" in flags or "a" not in flags else None

    errors: list[str] = []
    writes: dict[str, bytes | AsyncIterator[bytes]] = {}
    for target in await expand_operands(namespace, operands):
        if "h" in flags and namespace.is_link(target.virtual):
            await apply_link_attrs(
                dispatch, "touch", target, errors, mtime=stamp
            )
            continue
        if target.walk_error is not None:
            # Past -h, which acts on a looping link itself: the empty
            # name, whose `virtual` is the working directory, and a link
            # loop name nothing to touch. -c never opens the file, so it
            # meets the walk when it sets the times, where ENOENT is the
            # silent miss -c asks for.
            if "c" in flags and target.walk_error == "ENOENT":
                continue
            action = "setting times of" if "c" in flags else "cannot touch"
            errors.append(
                f"touch: {action} '{target.raw_path}': "
                f"{fs_strerror(walk_refusal(target))}\n"
            )
            continue
        if namespace.is_mount_root(target.virtual):
            errors.append(
                f"touch: cannot touch '{target.raw_path}': Is a directory\n"
            )
            continue
        refusal = await dot_refusal(
            partial(dispatch_stat, dispatch), target, namespace.follow
        )
        if refusal is not None:
            errors.append(
                f"touch: cannot touch '{target.raw_path}': "
                f"{fs_strerror(refusal)}\n"
            )
            continue
        resolved = follow_operand(
            namespace,
            "touch",
            "setting times of" if "c" in flags else "cannot touch",
            target,
            errors,
        )
        if resolved is None:
            continue
        # `x/` is `x/.`, so touch never creates through a trailing slash:
        # it sets times on a directory that has to be there already, and
        # GNU words that refusal ("setting times of") differently from
        # its create-path one ("cannot touch").
        if target.raw_path.endswith("/"):
            try:
                slashed, _ = await dispatch("stat", resolved)
            except FS_ERRORS as exc:
                errors.append(
                    f"touch: setting times of "
                    f"'{target.raw_path}': {fs_strerror(exc)}\n"
                )
                continue
            if slashed.type != FileType.DIRECTORY:
                errors.append(
                    f"touch: setting times of "
                    f"'{target.raw_path}': Not a directory\n"
                )
                continue
        try:
            try:
                await dispatch("stat", resolved)
            except NotADirectoryError as exc:
                # -c never opens the file, so GNU meets the bad parent
                # when it sets the times, and says so in those words.
                if "c" not in flags:
                    raise
                errors.append(
                    f"touch: setting times of "
                    f"'{target.raw_path}': {fs_strerror(exc)}\n"
                )
                continue
            except FileNotFoundError:
                if "c" in flags:
                    continue
                try:
                    await dispatch("write", resolved, data=b"")
                except OperationNotSupportedError:
                    # Stat-only backend (e.g. an API surface): creation is
                    # impossible, which GNU reports as EROFS. A read-only
                    # mount has already refused at the door, as for any
                    # write, so this is the writable mount's answer.
                    errors.append(
                        f"touch: cannot touch '{target.raw_path}': "
                        f"Read-only file system\n"
                    )
                    continue
                writes[resolved.virtual] = b""
                # A file touch creates is 0666 under the session's
                # umask; only a mask away from bash's default is worth
                # a mode write, since 644 is what a fresh file renders as.
                if session.umask != DEFAULT_UMASK:
                    await setattr_via(
                        dispatch,
                        resolved,
                        mode=0o666 & ~session.umask,
                        atime=atime,
                        mtime=mtime,
                    )
                    continue
            await setattr_via(dispatch, resolved, atime=atime, mtime=mtime)
        except PermissionError as exc:
            action = "setting times of" if "c" in flags else "cannot touch"
            errors.append(permission_error("touch", action, target, exc))
        except FS_ERRORS as exc:
            # A destination whose parent chain is not all directories is one
            # failed operand, not an aborted command: GNU reports it and
            # touches the rest. Caught here rather than around the write
            # because backends disagree about which call refuses first (an
            # object store answers stat with ENOENT and fails the write; a
            # filesystem or a keyed store answers stat itself with ENOTDIR).
            errors.append(
                f"touch: cannot touch '{target.raw_path}': "
                f"{fs_strerror(exc)}\n"
            )
    return finish("touch", errors, io=IOResult(writes=writes))
