import io
import tarfile

import pytest

from mirage.commands.builtin.generic.archive.types import Walked
from mirage.commands.builtin.generic.tar import (
    excluded,
    member_name,
    pruned,
    strip_prefix,
    tar,
)
from mirage.ops.types import LinkView, MountView
from mirage.types import (
    LINK_TARGET_KEY,
    ContentType,
    FileStat,
    FileType,
    MountMode,
    PathSpec,
)
from mirage.utils.key_prefix import mount_key
from mirage.vfs.ram import RAMVFS
from mirage.workspace import Workspace


def _spec(path: str, prefix: str = "") -> PathSpec:
    return PathSpec(
        vfs_path=mount_key(path, prefix),
        virtual=path,
        directory=path,
        resolved=True,
    )


def _raw(path: str, raw: str, prefix: str = "") -> PathSpec:
    return PathSpec(
        vfs_path=mount_key(path, prefix),
        virtual=path,
        directory=path,
        resolved=True,
        raw_path=raw,
    )


class _Tree:
    """A tiny in-memory backend: files by path, directories derived."""

    def __init__(self, files: dict[str, bytes], dirs: tuple[str, ...] = ()):
        self.files = dict(files)
        self.dirs = set(dirs)
        for path in files:
            parent = path.rsplit("/", 1)[0]
            while parent:
                self.dirs.add(parent)
                parent = parent.rsplit("/", 1)[0] if "/" in parent else ""

    async def read_bytes(self, path):
        key = path.virtual if isinstance(path, PathSpec) else path
        if key in getattr(self, "refused", ()):
            raise PermissionError(13, "frozen", key)
        if key not in self.files:
            raise FileNotFoundError(key)
        return self.files[key]

    async def write_bytes(self, path, data):
        self.files[path.virtual] = data

    async def mkdir(self, path, parents=False):
        self.dirs.add(path.virtual.rstrip("/"))

    async def stat(self, path):
        key = path.virtual.rstrip("/") or "/"
        if key in self.dirs:
            return FileStat(name=key, type=FileType.DIRECTORY)
        if key in self.files:
            return FileStat(
                name=key,
                type=FileType.FILE,
                content=ContentType.TEXT,
                size=len(self.files[key]),
            )
        raise FileNotFoundError(key)

    async def walk(self, path, find_type):
        base = path.virtual.rstrip("/") or "/"
        pool = self.dirs if find_type == "d" else self.files
        closed = getattr(self, "closed", ())
        return Walked(
            paths=tuple(
                sorted(
                    p
                    for p in pool
                    if (p == base or p.startswith(base.rstrip("/") + "/"))
                    and not any(p.startswith(c + "/") for c in closed)
                )
            ),
            unreadable=tuple(
                c for c in closed if c.startswith(base.rstrip("/") + "/")
            ),
        )

    async def is_dir(self, path):
        return (path.virtual.rstrip("/") or "/") in self.dirs


def _links(entries: dict[str, str]) -> LinkView:

    def stat_of(path):
        target = entries[path]
        return FileStat(
            name=path,
            type=FileType.SYMLINK,
            size=len(target),
            extra={LINK_TARGET_KEY: target},
        )

    async def target_stat(path):
        return None

    async def exists(path):
        return path in entries

    return LinkView(
        stat_at=lambda p: stat_of(p) if p in entries else None,
        children=lambda p: [],
        subtree=lambda p: [
            (k, stat_of(k))
            for k in sorted(entries)
            if k.startswith(p.rstrip("/") + "/")
        ],
        resolve=lambda p: entries.get(p, p),
        exists=exists,
        target_stat=target_stat,
    )


def _mounts(
    descendants: tuple[str, ...] = (), roots: tuple[str, ...] = ()
) -> MountView:

    def root_of(path):
        for root in sorted(roots, key=len, reverse=True):
            if path == root or path.startswith(root.rstrip("/") + "/"):
                return root
        return "/"

    return MountView(
        descendants=lambda p: [
            d for d in descendants if d.startswith(p.rstrip("/") + "/")
        ],
        visible_descendants=lambda p: [
            d for d in descendants if d.startswith(p.rstrip("/") + "/")
        ],
        is_root=lambda p: p.rstrip("/") in {r.rstrip("/") for r in roots},
        root_of=root_of,
    )


async def _create(tree: _Tree, paths, **flags):
    return await tar(
        paths,
        read_bytes=tree.read_bytes,
        write_bytes=tree.write_bytes,
        mkdir_fn=tree.mkdir,
        stat=tree.stat,
        walk=tree.walk,
        is_dir=tree.is_dir,
        **flags,
    )


def _names(archive: bytes) -> list[str]:
    with tarfile.open(fileobj=io.BytesIO(archive)) as tf:
        return [
            member.name + "/" if member.isdir() else member.name
            for member in tf.getmembers()
        ]


def test_excluded_matches_whole_name_and_every_component_suffix():
    assert excluded("d/a.txt", "d/a.txt")
    assert excluded("d/a.txt", "a.txt")
    assert excluded("d/sub/b.txt", "sub/b.txt")
    assert excluded("d/sub/b.txt", "*/b.txt")
    assert excluded("d/sub/", "sub")
    assert not excluded("d/a.txt", "b.txt")
    # The pattern is anchored at a component boundary, not mid-name.
    assert not excluded("d/abc.txt", "bc.txt")


def test_pruned_takes_the_children_of_an_excluded_directory():
    names = ["d/", "d/a.txt", "d/sub/", "d/sub/b.txt"]
    assert pruned(names, "sub") == ["d/", "d/a.txt"]
    assert pruned(names, "sub/b.txt") == ["d/", "d/a.txt", "d/sub/"]
    assert pruned(names, None) == names


@pytest.mark.parametrize(
    "path,kind,name",
    [
        ("/data/d/a.txt", "file", "data/d/a.txt"),
        ("/data/d", "dir", "data/d/"),
        ("d/", "dir", "d/"),
        ("link", "link", "link"),
        ("..", "dir", "./"),
        ("sub/..", "dir", "./"),
    ],
)
def test_member_name_strips_the_leading_slash_and_marks_directories(
    path: str, kind: str, name: str
):
    assert member_name(path, kind) == name


# Every row is GNU tar 1.35 on debian:stable-slim: `tar -cf` for the
# notice, `tar -tf` for the stored name.
STRIP_PREFIX_ROWS = [
    ("/data/sub/../file", "file", "/data/sub/../"),
    ("../file", "file", "../"),
    ("x/../y/f3", "y/f3", "x/../"),
    ("../../file", "file", "../../"),
    ("/data/../data/file", "data/file", "/data/../"),
    # No `..`, so the leading slash is the only thing tar refuses.
    ("/data/file", "data/file", "/"),
    # A `.` climbs nowhere, so GNU stores it and says nothing.
    ("./file", "./file", ""),
    ("d/a.txt", "d/a.txt", ""),
    # Nothing survives the traversal; `member_name` supplies the name.
    ("..", "", ".."),
    ("sub/..", "", "sub/.."),
]


@pytest.mark.parametrize("spelled,name,prefix", STRIP_PREFIX_ROWS)
def test_strip_prefix_drops_through_the_last_dotdot(
    spelled: str, name: str, prefix: str
):
    assert strip_prefix(spelled) == (name, prefix)


@pytest.mark.asyncio
async def test_create_keeps_an_empty_directory_as_its_own_member():
    tree = _Tree({"/d/a.txt": b"x"}, dirs=("/d", "/d/empty", "/out"))
    _, io_res = await _create(
        tree, [_raw("/d", "d")], c=True, f=_spec("/out.tar")
    )
    assert "d/empty/" in _names(io_res.writes["/out.tar"])


@pytest.mark.asyncio
async def test_create_reports_a_missing_operand_and_exits_two():
    tree = _Tree({"/d/a.txt": b"x"}, dirs=("/d",))
    _, io_res = await _create(
        tree,
        [_raw("/nope", "nope"), _raw("/d", "d")],
        c=True,
        f=_spec("/out.tar"),
    )
    assert io_res.exit_code == 2
    err = io_res.stderr.decode()
    assert "tar: nope: Cannot stat: No such file or directory" in err
    assert "Exiting with failure status due to previous errors" in err
    # GNU still archives every operand it could read.
    assert "d/a.txt" in _names(io_res.writes["/out.tar"])


@pytest.mark.asyncio
async def test_create_announces_before_a_later_operand_fails():
    tree = _Tree({"/base/file": b"x"}, dirs=("/base", "/base/sub"))
    _, io_res = await _create(
        tree,
        [_raw("/base/file", "../file"), _raw("/base/nope", "nope")],
        c=True,
        f=_spec("/out.tar"),
    )
    assert io_res.stderr.decode().splitlines()[:2] == [
        "tar: Removing leading `../' from member names",
        "tar: nope: Cannot stat: No such file or directory",
    ]


@pytest.mark.asyncio
async def test_create_refuses_an_empty_archive():
    tree = _Tree({})
    out, io_res = await _create(tree, [], c=True, f=_spec("/out.tar"))
    assert out is None
    assert io_res.exit_code == 2
    assert "Cowardly refusing" in io_res.stderr.decode()
    assert not io_res.writes


@pytest.mark.asyncio
async def test_create_stores_a_symlink_as_a_symlink():
    tree = _Tree({"/d/a.txt": b"a"}, dirs=("/d",))
    links = _links({"/d/link.txt": "a.txt"})
    _, io_res = await _create(
        tree, [_raw("/d", "d")], c=True, f=_spec("/out.tar"), links=links
    )
    with tarfile.open(fileobj=io.BytesIO(io_res.writes["/out.tar"])) as tf:
        link = tf.getmember("d/link.txt")
    assert link.issym()
    assert link.linkname == "a.txt"


@pytest.mark.asyncio
async def test_dereference_reports_a_dangling_link_and_exits_two():
    tree = _Tree({"/d/a.txt": b"alpha"}, dirs=("/d",))
    links = _links({"/d/bad": "/d/nope"})
    _, io_res = await _create(
        tree,
        [_raw("/d", "d")],
        c=True,
        h=True,
        f=_spec("/out.tar"),
        links=links,
    )
    assert io_res.exit_code == 2
    assert "tar: d/bad: Cannot stat" in io_res.stderr.decode()


@pytest.mark.asyncio
async def test_create_stops_at_a_nested_mount_and_says_so():
    tree = _Tree({"/d/a.txt": b"a"}, dirs=("/d", "/d/nested"))
    mounts = _mounts(descendants=("/d/nested",), roots=("/", "/d/nested"))
    _, io_res = await _create(
        tree, [_raw("/d", "d")], c=True, f=_spec("/out.tar"), mounts=mounts
    )
    assert io_res.exit_code == 0
    assert (
        "tar: d/nested/: file is on a different filesystem; not dumped"
        in io_res.stderr.decode()
    )
    # The mountpoint stays an entry; only its contents are left out.
    assert _names(io_res.writes["/out.tar"]) == ["d/", "d/a.txt", "d/nested/"]


@pytest.mark.asyncio
async def test_create_leaves_the_archive_out_of_itself():
    tree = _Tree({"/d/a.txt": b"a", "/d/old.tar": b"stale"}, dirs=("/d",))
    _, io_res = await _create(
        tree, [_raw("/d", "d")], c=True, f=_spec("/d/old.tar")
    )
    assert "archive cannot contain itself" in io_res.stderr.decode()
    assert _names(io_res.writes["/d/old.tar"]) == ["d/", "d/a.txt"]


@pytest.mark.asyncio
async def test_extract_recreates_directories_including_empty_ones():
    tree = _Tree({"/d/a.txt": b"x"}, dirs=("/d", "/d/empty", "/out"))
    _, io_res = await _create(
        tree, [_raw("/d", "d")], c=True, f=_spec("/out.tar")
    )
    tree.files["/out.tar"] = io_res.writes["/out.tar"]
    _, io_res = await _create(
        tree, [], x=True, f=_spec("/out.tar"), C=[_spec("/out")]
    )
    assert any("d/a.txt" in path for path in io_res.writes)
    assert "/out/d/empty" in tree.dirs


@pytest.mark.asyncio
async def test_requires_an_archive():
    tree = _Tree({"/a.txt": b"x"})
    with pytest.raises(ValueError, match="-f is required"):
        await _create(tree, [_spec("/a.txt")], c=True)


@pytest.mark.asyncio
async def test_a_symlink_operand_is_stored_as_a_symlink():
    """The router must not dereference it before the planner sees it."""
    tree = _Tree({"/d/a.txt": b"alpha"}, dirs=("/d",))
    links = _links({"/link": "/d/a.txt"})
    _, io_res = await _create(
        tree, [_raw("/link", "link")], c=True, f=_spec("/out.tar"), links=links
    )
    with tarfile.open(fileobj=io.BytesIO(io_res.writes["/out.tar"])) as tf:
        member = tf.getmember("link")
    assert member.issym()
    assert member.size == 0
    assert member.linkname == "/d/a.txt"


@pytest.mark.asyncio
async def test_create_reports_what_it_may_not_open_and_exits_two():
    # Pinned on GNU tar 1.35 (debian:stable-slim) over a mode-000 file
    # and directory: "Cannot open: Permission denied" for each, named as
    # the operand was typed, the directory's own entry kept, the file
    # left out, one trailer, exit 2. The scan's directory comes before
    # the write's file, a deliberate ordering: GNU interleaves them in
    # readdir order.
    tree = _Tree(
        {"/d/a.txt": b"x", "/d/locked/y": b"y", "/d/sealed/s": b"s"},
        dirs=("/d", "/d/locked", "/d/sealed"),
    )
    tree.closed = ("/d/sealed",)
    tree.refused = ("/d/locked/y",)
    _, io_res = await _create(
        tree, [_raw("/d", "/d")], c=True, f=_spec("/out.tar")
    )
    assert io_res.exit_code == 2
    assert io_res.stderr.decode() == (
        "tar: Removing leading `/' from member names\n"
        "tar: /d/sealed: Cannot open: Permission denied\n"
        "tar: /d/locked/y: Cannot open: Permission denied\n"
        "tar: Exiting with failure status due to previous errors\n"
    )
    assert _names(io_res.writes["/out.tar"]) == [
        "d/",
        "d/a.txt",
        "d/locked/",
        "d/sealed/",
    ]


def _tar_bytes(name: str, data: bytes) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as archive:
        info = tarfile.TarInfo(name)
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _read_only_tar_mount() -> tuple[Workspace, RAMVFS]:
    vfs = RAMVFS()
    vfs._store.files["/f.txt"] = b"hello\n"
    vfs._store.files["/a.tar"] = _tar_bytes("g.txt", b"hello\n")
    return Workspace(
        {
            "/ro/": (vfs, MountMode.READ),
            "/rw/": (RAMVFS(), MountMode.WRITE),
        }
    ), vfs


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "line,stdout",
    [
        ("tar -tf /ro/a.tar", b"g.txt\n"),
        ("cd /ro && tar tf a.tar", b"g.txt\n"),
        ("tar -xOf /ro/a.tar", b"hello\n"),
        ("tar -x --to-stdout -f /ro/a.tar", b"hello\n"),
        ("tar -xf /ro/a.tar -C /rw && cat /rw/g.txt", b"hello\n"),
    ],
)
async def test_a_read_only_mount_runs_tar_where_it_writes_nothing(
    line: str, stdout: bytes
):
    ws, vfs = _read_only_tar_mount()
    before = dict(vfs._store.files)
    result = await ws.shell(line)
    assert (result.exit_code, await result.materialize_stdout()) == (0, stdout)
    assert vfs._store.files == before


_EXTRACT_REFUSED = (
    b"tar: g.txt: Cannot open: Read-only file system\n"
    b"tar: Exiting with failure status due to previous "
    b"errors\n"
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "line,stderr",
    [
        ("cd /ro && tar -xf a.tar", _EXTRACT_REFUSED),
        ("cd /ro && tar xf a.tar", _EXTRACT_REFUSED),
        (
            "tar -cf /ro/b.tar /ro/f.txt",
            b"tar: /ro/b.tar: Cannot open: Read-only file system\n"
            b"tar: Error is not recoverable: exiting now\n",
        ),
    ],
)
async def test_a_read_only_mount_refuses_tar_at_the_write(
    line: str, stderr: bytes
):
    # GNU tar 1.35 on a read-only filesystem: each member it cannot
    # create is its own line and the run goes on; an archive it cannot
    # create is fatal before any member is read.
    ws, vfs = _read_only_tar_mount()
    before = dict(vfs._store.files)
    result = await ws.shell(line)
    assert (result.exit_code, result.stderr) == (2, stderr)
    assert vfs._store.files == before


_FATAL = "tar: Error is not recoverable: exiting now\n"
_CHILD_FATAL = (
    "tar (child): Error is not recoverable: exiting now\n",
    "tar: Child returned status 2\n" + _FATAL,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "line, want",
    [
        (
            "tar -tf nope.tar",
            "tar: nope.tar: Cannot open: No such file or directory\n" + _FATAL,
        ),
        (
            "tar -xf d",
            "tar: d: Cannot read: Is a directory\n"
            "tar: At beginning of tape, quitting now\n" + _FATAL,
        ),
        (
            "tar -tzf nope.tgz",
            "tar (child): nope.tgz: Cannot open: No such file or directory\n"
            + _CHILD_FATAL[0]
            + _CHILD_FATAL[1],
        ),
        (
            "tar -tzf d",
            "tar (child): d: Cannot read: Is a directory\n"
            "tar (child): At beginning of tape, quitting now\n"
            + _CHILD_FATAL[0]
            + "\ngzip: stdin: unexpected end of file\n"
            + _CHILD_FATAL[1],
        ),
        (
            "tar -czf d a",
            "tar (child): d: Cannot open: Is a directory\n"
            + _CHILD_FATAL[0]
            + _CHILD_FATAL[1],
        ),
    ],
)
async def test_an_archive_tar_cannot_open_is_named_as_typed(line, want):
    # tar 1.35 names -f as typed. A directory opens and fails the first
    # read, where a backend keying files alone reports it absent. With a
    # compressor tar's child speaks, the reading one's gzip meets an empty
    # pipe unless the name was missing, and tar reports the child's status.
    ws = Workspace({"/data": RAMVFS()}, mode=MountMode.WRITE)
    await ws.shell("mkdir -p /data/d && printf a > /data/a")
    r = await ws.shell(f"cd /data && {line}")
    assert r.exit_code == 2
    assert await r.stderr_str() == want
