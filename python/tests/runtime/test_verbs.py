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

import inspect
import os

from mirage.errors import FsCondition
from mirage.runtime.verbs import (
    CLASSIFIED_VERBS,
    PASSTHROUGH_VERBS,
    REFUSED_VERBS,
    ROUTED_VERBS,
    refusal_of,
)

# Parameter names CPython's os module gives an argument that can carry a
# path. `utime` is probed separately because its C signature is not
# introspectable, so the sweep below cannot see it.
PATH_PARAMS = frozenset(
    {
        "path",
        "src",
        "dst",
        "top",
        "source",
        "target",
        "link",
        "old",
        "new",
        "filename",
        "file",
        "name",
        "paths",
        "entry",
        "dirname",
    }
)
UNINTROSPECTABLE = frozenset({"utime"})

# Names one platform has and another does not, so the existence check
# below cannot demand them. The BSD flag verbs and `lchmod` are macOS
# only; the xattr family, `memfd_create`, `splice` and
# `copy_file_range` are linux only.
PLATFORM_SPECIFIC = frozenset(
    {
        "chflags",
        "copy_file_range",
        "getxattr",
        "lchflags",
        "lchmod",
        "listxattr",
        "memfd_create",
        "removexattr",
        "setxattr",
        "splice",
    }
)

# What the sweep below reports on linux, which is what CI runs. Frozen
# here so a macOS run catches a linux-only gap; regenerate with the
# sweep under `docker run --rm python:3.12-slim`.
LINUX_PATH_TAKING = frozenset(
    {
        "access",
        "chdir",
        "chmod",
        "chown",
        "chroot",
        "confstr",
        "copy_file_range",
        "execl",
        "execle",
        "execlp",
        "execlpe",
        "execv",
        "execve",
        "execvp",
        "execvpe",
        "fpathconf",
        "fsdecode",
        "fsencode",
        "fspath",
        "fwalk",
        "getxattr",
        "lchown",
        "link",
        "listdir",
        "listxattr",
        "lstat",
        "makedirs",
        "memfd_create",
        "mkdir",
        "mkfifo",
        "mknod",
        "open",
        "pathconf",
        "putenv",
        "readlink",
        "remove",
        "removedirs",
        "removexattr",
        "rename",
        "renames",
        "replace",
        "rmdir",
        "scandir",
        "setxattr",
        "spawnl",
        "spawnle",
        "spawnlp",
        "spawnlpe",
        "spawnv",
        "spawnve",
        "spawnvp",
        "spawnvpe",
        "splice",
        "stat",
        "statvfs",
        "symlink",
        "sysconf",
        "truncate",
        "unlink",
        "unsetenv",
        "utime",
        "walk",
    }
)


def _path_taking_os_names() -> set[str]:
    found: set[str] = set(UNINTROSPECTABLE)
    for name in dir(os):
        if name.startswith("_"):
            continue
        fn = getattr(os, name)
        if not callable(fn):
            continue
        try:
            sig = inspect.signature(fn)
        except (ValueError, TypeError):
            continue
        if set(sig.parameters) & PATH_PARAMS:
            found.add(name)
    return found


class TestVerbCoverage:
    def test_every_path_taking_os_name_is_classified(self):
        # Default-deny means an unclassified name is refused, so this
        # failing is not a silent hole; it is a name whose answer nobody
        # decided. Put it in one of the three tables.
        missing = sorted(_path_taking_os_names() - CLASSIFIED_VERBS)
        assert missing == []

    def test_tables_are_disjoint(self):
        assert not (frozenset(ROUTED_VERBS) & frozenset(REFUSED_VERBS))
        assert not (frozenset(ROUTED_VERBS) & PASSTHROUGH_VERBS)
        assert not (frozenset(REFUSED_VERBS) & PASSTHROUGH_VERBS)

    def test_the_linux_sweep_is_classified_too(self):
        # CI runs linux and development runs macOS, so the two name sets
        # differ; without this the gap only shows up in CI.
        assert sorted(LINUX_PATH_TAKING - CLASSIFIED_VERBS) == []

    def test_every_classified_name_exists_in_os(self):
        # A typo'd row would classify a verb no guest can ever spell,
        # leaving the real one to the default-deny path.
        missing = [
            n
            for n in CLASSIFIED_VERBS - PLATFORM_SPECIFIC
            if not hasattr(os, n)
        ]
        assert sorted(missing) == []


class TestRefusalOf:
    def test_routed_verb_is_served(self):
        assert refusal_of("symlink") is None

    def test_passthrough_verb_is_served(self):
        assert refusal_of("execv") is None

    def test_refused_verb_carries_its_condition(self):
        assert refusal_of("link") is FsCondition.EPERM

    def test_unknown_verb_defaults_to_enotsup(self):
        assert refusal_of("teleport") is FsCondition.ENOTSUP
