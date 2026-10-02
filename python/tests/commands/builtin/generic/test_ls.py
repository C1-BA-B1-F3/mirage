import asyncio
import errno
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from functools import partial
from operator import attrgetter

import pytest

from mirage.commands.builtin.generic.ls import (
    LS_FAILURE,
    LS_MINOR_PROBLEM,
    LS_OK,
    LsWarning,
    exit_status_for,
    filevercmp,
    format_simple,
    indicator_flag,
    ls,
    parse_flags,
    sort_stats,
    type_indicator,
    walk,
)
from mirage.commands.builtin.utils.formatting import BlockSize, LsColumns
from mirage.commands.errors import CommandTimeoutError, UsageError
from mirage.commands.spec import SPECS, parse_command, parse_to_kwargs
from mirage.commands.spec.flag_view import FlagView
from mirage.ops.types import MountView
from mirage.types import (
    ContentType,
    FileStat,
    FileType,
    LsIndicator,
    LsSortBy,
    LsTimeKind,
    PathSpec,
)


def _spec(path: str) -> PathSpec:
    return PathSpec(virtual=path, directory=path, vfs_path=path.strip("/"))


def _make_fs_backend(tree: dict[str, FileStat]):
    """Build (readdir, stat) callables over an in-memory entry tree.

    `tree` maps absolute path → FileStat. Directories are entries whose
    type == FileType.DIRECTORY. readdir lists direct children of the path.
    """

    async def stat(p: PathSpec, index=None) -> FileStat:
        if p.virtual not in tree:
            raise FileNotFoundError(p.virtual)
        return tree[p.virtual]

    async def readdir(p: PathSpec, _index=None) -> list[str]:
        if p.virtual not in tree:
            raise FileNotFoundError(p.virtual)
        if tree[p.virtual].type != FileType.DIRECTORY:
            raise ValueError(f"not a directory: {p.virtual}")
        prefix = p.virtual.rstrip("/") + "/"
        children: list[str] = []
        for key in tree:
            if key == p.virtual:
                continue
            if key.startswith(prefix):
                remainder = key[len(prefix) :]
                if "/" not in remainder:
                    children.append(key)
        return sorted(children)

    return readdir, stat


async def _stat_denying(
    p: PathSpec,
    index=None,
    *,
    stat: Callable[..., Awaitable[FileStat]],
    blocked: str,
) -> FileStat:
    if p.virtual == blocked:
        raise PermissionError(13, "Permission denied")
    return await stat(p, index)


async def _readdir_denying(
    p: PathSpec,
    index=None,
    *,
    readdir: Callable[..., Awaitable[list[str]]],
    blocked: str,
) -> list[str]:
    if p.virtual == blocked:
        raise PermissionError(13, "Permission denied")
    return await readdir(p, index)


def _file(name: str, size: int = 0, modified: str | None = None) -> FileStat:
    return FileStat(
        name=name,
        size=size,
        modified=modified,
        type=FileType.FILE,
        content=ContentType.TEXT,
    )


def _dir(name: str) -> FileStat:
    return FileStat(name=name, size=None, type=FileType.DIRECTORY)


def test_format_simple_default_lists_names():
    out = format_simple([_file("a.txt"), _file("b.txt")])
    assert out == ["a.txt", "b.txt"]


def test_format_simple_classify_marks_dirs_with_slash():
    out = format_simple(
        [_file("a.txt"), _dir("sub")], indicator=LsIndicator.CLASSIFY
    )
    assert out == ["a.txt", "sub/"]


@pytest.mark.asyncio
async def test_walk_stats_one_entry_at_a_time():
    # On a mount that keeps no listing index each entry's stat is a
    # backend request; a whole directory's worth at once is a burst.
    tree = {"/dir": _dir("dir")}
    tree.update({f"/dir/{i}.json": _file(f"{i}.json") for i in range(40)})
    readdir, stat = _make_fs_backend(tree)
    flight = {"now": 0, "peak": 0}

    async def slow_stat(p: PathSpec, index=None) -> FileStat:
        flight["now"] += 1
        flight["peak"] = max(flight["peak"], flight["now"])
        await asyncio.sleep(0.001)
        flight["now"] -= 1
        return await stat(p, index)

    res = await walk(_spec("/dir"), readdir=readdir, stat=slow_stat)
    assert len(res.entries) == 40
    assert flight["peak"] == 1


@pytest.mark.asyncio
async def test_walk_skips_dotfiles_unless_all_files():
    tree = {
        "/dir": _dir("dir"),
        "/dir/.hidden": _file(".hidden", 1),
        "/dir/visible.txt": _file("visible.txt", 2),
    }
    readdir, stat = _make_fs_backend(tree)
    res = await walk(_spec("/dir"), readdir=readdir, stat=stat)
    entries = res.entries
    assert [e.name for e in entries] == ["visible.txt"]
    res = await walk(_spec("/dir"), readdir=readdir, stat=stat, all_files=True)
    entries = res.entries
    assert sorted(e.name for e in entries) == [".hidden", "visible.txt"]


@pytest.mark.asyncio
async def test_ls_missing_operand_exits_2_even_beside_a_good_one():
    """GNU ratchets to 2 for any bad command-line operand, and still lists
    the good ones. Order must not matter. Two operands means the survivor is
    still headed, exactly as GNU prints it.
    """
    tree = {"/dir": _dir("dir"), "/dir/a.txt": _file("a.txt")}
    readdir, stat = _make_fs_backend(tree)
    for paths in (
        [_spec("/nope"), _spec("/dir")],
        [_spec("/dir"), _spec("/nope")],
    ):
        output, io = await ls(paths, readdir=readdir, stat=stat)
        assert io.exit_code == LS_FAILURE
        assert output == b"/dir:\na.txt\n"


@pytest.mark.asyncio
async def test_ls_missing_operand_under_list_dir_exits_2():
    tree = {"/dir": _dir("dir")}
    readdir, stat = _make_fs_backend(tree)
    _, io = await ls(
        [_spec("/dir"), _spec("/nope")],
        readdir=readdir,
        stat=stat,
        list_dir=True,
    )
    assert io.exit_code == LS_FAILURE


@pytest.mark.asyncio
async def test_ls_unstattable_entry_is_a_minor_problem():
    """An entry below the operand is not a command-line arg, so GNU keeps
    listing its siblings, keeps the entry's own row of ``?``, and exits 1.
    """
    tree = {
        "/dir": _dir("dir"),
        "/dir/a.txt": _file("a.txt"),
        "/dir/locked.txt": _file("locked.txt"),
    }
    readdir, stat = _make_fs_backend(tree)

    denying_stat = partial(_stat_denying, stat=stat, blocked="/dir/locked.txt")
    output, io = await ls(
        [_spec("/dir")], readdir=readdir, stat=denying_stat, long=True
    )
    assert io.exit_code == LS_MINOR_PROBLEM
    assert output.decode().endswith("? locked.txt\n")
    assert b"locked.txt" in (io.stderr or b"")


def _failing_entry(exc: Exception):
    """A readdir/stat pair over /dir whose b.txt fails its stat.

    Args:
        exc (Exception): what b.txt's stat raises.
    """
    tree = {
        "/dir": _dir("dir"),
        "/dir/a.txt": _file("a.txt", 1, "2026-01-01T00:00:00Z"),
        "/dir/b.txt": _file("b.txt", 1, "2026-01-01T00:00:00Z"),
    }
    readdir, stat = _make_fs_backend(tree)

    async def failing_stat(p: PathSpec, index=None) -> FileStat:
        if p.virtual == "/dir/b.txt":
            raise exc
        return await stat(p, index)

    return readdir, failing_stat


# GNU (coreutils 9.7, EIO injected on one entry with strace) lists every
# name, and only a listing that stats the entry (-l, -F, -t, -i ...)
# reports it, whatever the errno, and exits 1.
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exc, flags, row, stderr",
    [
        (FileNotFoundError("/dir/b.txt"), {}, "b.txt", b""),
        (RuntimeError("upstream 502 Bad Gateway"), {}, "b.txt", b""),
        (
            FileNotFoundError("/dir/b.txt"),
            {"long": True},
            "?????????? ? ? ? ?            ? b.txt",
            b"ls: cannot access '/dir/b.txt': No such file or directory\n",
        ),
        (
            RuntimeError("S3 GET b.txt failed: 403 Forbidden"),
            {"indicator": LsIndicator.CLASSIFY},
            "b.txt",
            b"ls: cannot access '/dir/b.txt': S3 GET b.txt failed: 403 Forbidden\n",
        ),
        (
            OSError(errno.EIO, "socket hang up"),
            {"long": True},
            "?????????? ? ? ? ?            ? b.txt",
            b"ls: cannot access '/dir/b.txt': Input/output error\n",
        ),
    ],
)
async def test_ls_lists_an_unstattable_entry(exc, flags, row, stderr):
    readdir, stat = _failing_entry(exc)
    output, io = await ls([_spec("/dir")], readdir=readdir, stat=stat, **flags)
    *_, sibling, last = output.decode().splitlines()
    assert sibling.endswith("a.txt") and last == row
    assert (io.stderr or b"") == stderr
    assert io.exit_code == (LS_MINOR_PROBLEM if stderr else LS_OK)


# GNU (coreutils 9.7, both entries' stat denied) zeroes a failed stat, so
# -S sorts the rows as size 0 even where readdir marked a directory.
@pytest.mark.asyncio
async def test_ls_size_sort_counts_an_unstattable_directory_as_zero():
    tree = {
        "/d": _dir("d"),
        "/d/afile": _file("afile", 5000, "2026-01-01T00:00:00Z"),
        "/d/zdir": _dir("zdir"),
    }
    readdir, stat = _make_fs_backend(tree)

    async def marking_readdir(p: PathSpec, index=None) -> list[str]:
        return [
            f"{e}/" if tree[e].type == FileType.DIRECTORY else e
            for e in await readdir(p, index)
        ]

    async def denying_stat(p: PathSpec, index=None) -> FileStat:
        if p.virtual != "/d":
            raise PermissionError(errno.EACCES, "Permission denied")
        return await stat(p, index)

    output, io = await ls(
        [_spec("/d")],
        readdir=marking_readdir,
        stat=denying_stat,
        sort_by=LsSortBy.SIZE,
    )
    assert io.exit_code == LS_MINOR_PROBLEM
    assert output == b"afile\nzdir\n"


@pytest.mark.asyncio
async def test_ls_still_ends_on_a_timeout():
    readdir, stat = _failing_entry(CommandTimeoutError("stat", 5))
    with pytest.raises(CommandTimeoutError):
        await ls([_spec("/dir")], readdir=readdir, stat=stat)


@pytest.mark.asyncio
async def test_ls_still_propagates_the_operands_own_failure():
    _, stat = _failing_entry(RuntimeError("socket hang up"))

    async def readdir(p: PathSpec, _index=None) -> list[str]:
        raise RuntimeError("socket hang up")

    with pytest.raises(RuntimeError, match="socket hang up"):
        await ls([_spec("/dir")], readdir=readdir, stat=stat)


@pytest.mark.asyncio
async def test_ls_serious_problem_outranks_a_minor_one():
    tree = {
        "/dir": _dir("dir"),
        "/dir/a.txt": _file("a.txt"),
        "/dir/sub": _dir("sub"),
    }
    readdir, stat = _make_fs_backend(tree)

    denying_readdir = partial(
        _readdir_denying, readdir=readdir, blocked="/dir/sub"
    )
    _, io = await ls(
        [_spec("/dir"), _spec("/nope")],
        readdir=denying_readdir,
        stat=stat,
        recursive=True,
    )
    assert io.exit_code == LS_FAILURE


@pytest.mark.asyncio
async def test_ls_recursive_prints_no_header_for_a_failed_operand():
    tree = {"/dir": _dir("dir"), "/dir/a.txt": _file("a.txt")}
    readdir, stat = _make_fs_backend(tree)
    output, io = await ls(
        [_spec("/dir"), _spec("/nope")],
        readdir=readdir,
        stat=stat,
        recursive=True,
    )
    assert io.exit_code == LS_FAILURE
    assert b"/nope:" not in output
    assert b"/dir:" in output


@pytest.mark.asyncio
async def test_ls_recursive_failed_operand_first_has_no_leading_blank():
    """A failed operand renders no group, so the next one still starts the
    output flush left, the same both operand orders.
    """
    tree = {"/dir": _dir("dir"), "/dir/a.txt": _file("a.txt")}
    readdir, stat = _make_fs_backend(tree)
    output, io = await ls(
        [_spec("/nope"), _spec("/dir")],
        readdir=readdir,
        stat=stat,
        recursive=True,
    )
    assert io.exit_code == LS_FAILURE
    assert output == b"/dir:\na.txt\n"


def test_exit_status_for_ratchets_like_gnu():
    minor = LsWarning("ls: cannot access 'x': Permission denied", False)
    serious = LsWarning("ls: cannot access '/nope': No such file", True)
    assert exit_status_for([]) == LS_OK
    assert exit_status_for([minor]) == LS_MINOR_PROBLEM
    assert exit_status_for([serious]) == LS_FAILURE
    assert exit_status_for([minor, serious]) == LS_FAILURE
    assert exit_status_for([serious, minor]) == LS_FAILURE


@pytest.mark.asyncio
async def test_walk_empty_readdir_falls_back_to_file():
    """Object stores (e.g. s3) return [] for a file key instead of raising."""
    fstat = _file("a.parquet", 5)

    async def stat(p, index=None):
        if p.virtual == "/data/a.parquet":
            return fstat
        raise FileNotFoundError(p.virtual)

    async def readdir(p, _index=None):
        return []

    res = await walk(_spec("/data/a.parquet"), readdir=readdir, stat=stat)
    entries = res.entries
    warnings = [w.message for w in res.warnings]
    assert [e.name for e in entries] == ["/data/a.parquet"]
    assert warnings == []


def _two_dir_tree() -> dict[str, FileStat]:
    return {
        "/a": _dir("a"),
        "/a/f.txt": _file("f.txt", 3),
        "/a/sub": _dir("sub"),
        "/b": _dir("b"),
        "/b/g.txt": _file("g.txt", 3),
        "/c": _dir("c"),
        "/mfile": _file("mfile", 1),
        "/zfile": _file("zfile", 1),
    }


@pytest.mark.asyncio
async def test_ls_empty_dir_operand_still_gets_a_header():
    readdir, stat = _make_fs_backend(_two_dir_tree())
    output, _ = await ls(
        [_spec("/b"), _spec("/c")], readdir=readdir, stat=stat
    )
    assert output == b"/b:\ng.txt\n\n/c:\n"


@pytest.mark.asyncio
async def test_ls_reverse_flips_operand_and_entry_order():
    readdir, stat = _make_fs_backend(_two_dir_tree())
    output, _ = await ls(
        [_spec("/a"), _spec("/b")], readdir=readdir, stat=stat, reverse=True
    )
    assert output == b"/b:\ng.txt\n\n/a:\nsub\nf.txt\n"


@pytest.mark.asyncio
async def test_ls_repeated_operand_lists_twice():
    readdir, stat = _make_fs_backend(_two_dir_tree())
    output, _ = await ls(
        [_spec("/a"), _spec("/a")], readdir=readdir, stat=stat
    )
    assert output == b"/a:\nf.txt\nsub\n\n/a:\nf.txt\nsub\n"


@pytest.mark.asyncio
async def test_ls_recursive_file_operand_is_not_headed():
    readdir, stat = _make_fs_backend(_two_dir_tree())
    output, _ = await ls(
        [_spec("/a"), _spec("/zfile")],
        readdir=readdir,
        stat=stat,
        recursive=True,
    )
    assert output == b"/zfile\n\n/a:\nf.txt\nsub\n\n/a/sub:\n"


def _tied_tree() -> dict[str, FileStat]:
    stamp = datetime(2024, 1, 1, tzinfo=timezone.utc).isoformat()
    return {
        "/a": _file("a", 2, modified=stamp),
        "/b": _file("b", 2, modified=stamp),
        "/c": _file("c", 2, modified=stamp),
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("sort_by", [LsSortBy.TIME, LsSortBy.SIZE])
async def test_ls_tied_operands_break_on_name(sort_by):
    """GNU's -t/-S comparators fall back to the name on a tie."""
    readdir, stat = _make_fs_backend(_tied_tree())
    output, _ = await ls(
        [_spec("/c"), _spec("/a"), _spec("/b")],
        readdir=readdir,
        stat=stat,
        sort_by=sort_by,
    )
    assert output == b"/a\n/b\n/c\n"


@pytest.mark.asyncio
@pytest.mark.parametrize("sort_by", [LsSortBy.TIME, LsSortBy.SIZE])
async def test_ls_reverse_flips_the_tie_break_too(sort_by):
    """`-r` negates the whole comparison, so tied names come out descending."""
    readdir, stat = _make_fs_backend(_tied_tree())
    output, _ = await ls(
        [_spec("/c"), _spec("/a"), _spec("/b")],
        readdir=readdir,
        stat=stat,
        sort_by=sort_by,
        reverse=True,
    )
    assert output == b"/c\n/b\n/a\n"


@pytest.mark.asyncio
@pytest.mark.parametrize("sort_by", [LsSortBy.TIME, LsSortBy.SIZE])
async def test_ls_tied_entries_break_on_name(sort_by):
    stamp = datetime(2024, 1, 1, tzinfo=timezone.utc).isoformat()
    tree = {
        "/dir": _dir("dir"),
        "/dir/b.txt": _file("b.txt", 2, modified=stamp),
        "/dir/a.txt": _file("a.txt", 2, modified=stamp),
    }
    readdir, stat = _make_fs_backend(tree)
    output, _ = await ls(
        [_spec("/dir")], readdir=readdir, stat=stat, sort_by=sort_by
    )
    assert output == b"a.txt\nb.txt\n"
    output, _ = await ls(
        [_spec("/dir")],
        readdir=readdir,
        stat=stat,
        sort_by=sort_by,
        reverse=True,
    )
    assert output == b"b.txt\na.txt\n"


@pytest.mark.asyncio
async def test_ls_long_widths_are_per_directory_block():
    tree = {
        "/a": _dir("a"),
        "/a/big.txt": _file("big.txt", 1000),
        "/b": _dir("b"),
        "/b/small.txt": _file("small.txt", 1),
    }
    readdir, stat = _make_fs_backend(tree)
    output, _ = await ls(
        [_spec("/a"), _spec("/b")], readdir=readdir, stat=stat, long=True
    )
    lines = output.decode().splitlines()
    assert lines[0] == "/a:"
    assert " 1000 " in lines[2]
    assert lines[3] == ""
    assert lines[4] == "/b:"
    # GNU sizes its columns per block, so /b is not padded to /a's width.
    assert " 1 " in lines[6]
    assert "    1 " not in lines[6]


def _mount_view(*roots: str) -> MountView:
    """A mount table holding exactly ``roots``.

    Only ``is_root`` is exercised: it is what tells a nested mount's root
    (whose listing belongs to another backend) from a directory the
    namespace merely owes children, which -R must still descend.
    """
    return MountView(
        descendants=lambda p: [
            r for r in roots if r.startswith(p.rstrip("/") + "/")
        ],
        visible_descendants=lambda p: [
            r for r in roots if r.startswith(p.rstrip("/") + "/")
        ],
        is_root=lambda p: p.rstrip("/") in roots,
        root_of=lambda p: "/",
    )


@pytest.mark.asyncio
async def test_structure_only_chain_descends_under_recursive():
    """A structure chain (a link's ancestors) continues below the first
    level, so -R descends it: only a mount root stops the walk."""

    async def readdir(p, index=None):
        raise FileNotFoundError(p.virtual)

    async def stat(p, index=None):
        raise FileNotFoundError(p.virtual)

    def child_mounts(parent: str) -> list[str]:
        if parent == "/ghost":
            return ["deep"]
        if parent == "/ghost/deep":
            return ["lnk"]
        return []

    out, io = await ls(
        [PathSpec.from_str_path("/ghost")],
        readdir=readdir,
        stat=stat,
        recursive=True,
        child_mounts=child_mounts,
        mounts=_mount_view("/ghost/deep/lnk"),
    )
    assert io.exit_code == 0
    assert out.decode() == "/ghost:\ndeep\n\n/ghost/deep:\nlnk\n"


@pytest.mark.asyncio
async def test_a_child_mount_serving_one_file_is_not_a_directory_row():
    """A mount root is not always a directory.

    Every workspace mounts `/.bash_history` as a whole mount serving one
    file, and no backend can stat it: the parent's cannot see into the
    child mount and the child's own calls its root `/`. Synthesizing the
    row as a directory suffixed it with `/` under -F, rendered it
    `drwxr-xr-x` under -l, and offered it to -R as something to descend.
    GNU (coreutils 9.7, `mount --bind` of one file onto another) lists it
    as an ordinary file row of its parent.
    """
    tree = {
        "/base": _dir("base"),
        "/base/top.txt": _file("top.txt", 2),
    }
    readdir, stat = _make_fs_backend(tree)

    async def stat_path(virtual: str) -> FileStat | None:
        if virtual != "/base/hist":
            return None
        # The child mount answers its own root with its name for it.
        return _file("/", 7)

    out, io = await ls(
        [PathSpec.from_str_path("/base")],
        readdir=readdir,
        stat=stat,
        recursive=True,
        indicator=LsIndicator.CLASSIFY,
        child_mounts=lambda d: ["hist"] if d == "/base" else [],
        mounts=_mount_view("/base/hist"),
        stat_path=stat_path,
    )
    assert io.exit_code == 0
    assert out.decode() == "/base:\nhist\ntop.txt\n"


@pytest.mark.asyncio
async def test_a_child_mount_row_falls_back_to_directory_with_no_dispatcher():
    """Absence of the door can only mean "nobody can answer", so the row
    keeps the shape every caller outside a workspace already saw."""
    tree = {"/base": _dir("base")}
    readdir, stat = _make_fs_backend(tree)
    out, io = await ls(
        [PathSpec.from_str_path("/base")],
        readdir=readdir,
        stat=stat,
        indicator=LsIndicator.CLASSIFY,
        child_mounts=lambda d: ["hist"] if d == "/base" else [],
    )
    assert io.exit_code == 0
    assert out.decode() == "hist/\n"


# ── the flag set beyond -l: sort orders, columns, time styles ──────────


def test_unsorted_keeps_the_listing_order_and_ignores_grouping():
    rows = [_file("b"), _dir("d"), _file("a")]
    assert [s.name for s in sort_stats(rows, LsSortBy.NONE, False)] == [
        "b",
        "d",
        "a",
    ]
    assert [
        s.name
        for s in sort_stats(rows, LsSortBy.NONE, False, group_dirs_first=True)
    ] == ["b", "d", "a"]
    # -r reverses while sorting, and -U does not sort (GNU: `ls -Ur`
    # lists exactly what `ls -U` lists).
    assert [s.name for s in sort_stats(rows, LsSortBy.NONE, True)] == [
        "b",
        "d",
        "a",
    ]


def test_width_sort_orders_by_rendered_width_then_name():
    rows = [_file("ccc"), _file("b"), _file("aa"), _file("a")]
    assert [s.name for s in sort_stats(rows, LsSortBy.WIDTH, False)] == [
        "a",
        "b",
        "aa",
        "ccc",
    ]
    # Pinned on coreutils 9.7 under C.UTF-8: a wide character counts two
    # columns and a combining mark none.
    names = ["界", "aa", "é", "a", "e\u0301x"]
    rows = [_file(n) for n in names]
    assert [s.name for s in sort_stats(rows, LsSortBy.WIDTH, False)] == [
        "a",
        "é",
        "aa",
        "e\u0301x",
        "界",
    ]


def test_filevercmp_pins_gnu_corner_cases():
    assert filevercmp("file2.txt", "file10.txt") < 0
    assert filevercmp("a.txt", "a.tar.gz") > 0
    assert filevercmp("", "a") < 0
    assert filevercmp(".", "..") < 0
    assert filevercmp(".hidden", "a") < 0
    assert filevercmp("1.0~rc1", "1.0") < 0
    assert filevercmp("abc", "abc") == 0


def test_filevercmp_orders_bytes_past_the_letters():
    # Pinned on coreutils 9.7 under LC_ALL=C: `_ { é ÿ Ā €` and
    # `a- a{ aé`, since gnulib classifies bytes, not code points.
    assert filevercmp("_", "{") < 0
    assert filevercmp("{", "é") < 0
    assert filevercmp("é", "ÿ") < 0
    assert filevercmp("ÿ", "Ā") < 0
    assert filevercmp("Ā", "€") < 0
    assert filevercmp("a-", "a{") < 0
    assert filevercmp("a{", "aé") < 0
    assert filevercmp("\uffff", "\U0001d11e") < 0


@pytest.mark.asyncio
async def test_access_time_sorts_and_shows_under_u():
    tree = {
        "/t": _dir("t"),
        "/t/old.txt": FileStat(
            name="old.txt",
            size=1,
            modified="2025-01-01T00:00:00Z",
            atime="2025-06-01T00:00:00Z",
            type=FileType.FILE,
        ),
        "/t/new.txt": FileStat(
            name="new.txt",
            size=1,
            modified="2025-03-01T00:00:00Z",
            atime="2025-02-01T00:00:00Z",
            type=FileType.FILE,
        ),
    }
    readdir, stat = _make_fs_backend(tree)
    output, _ = await ls(
        [_spec("/t")],
        readdir=readdir,
        stat=stat,
        sort_by=LsSortBy.TIME,
        time_kind=LsTimeKind.ATIME,
    )
    assert output.decode().split() == ["old.txt", "new.txt"]
    output, _ = await ls(
        [_spec("/t")],
        readdir=readdir,
        stat=stat,
        long=True,
        columns=LsColumns(
            owner=False,
            group=False,
            time_kind=LsTimeKind.ATIME,
            time_style="long-iso",
        ),
    )
    assert output.decode().splitlines() == [
        "total ?",
        "-rw-r--r-- 1 1 2025-02-01 00:00 new.txt",
        "-rw-r--r-- 1 1 2025-06-01 00:00 old.txt",
    ]


@pytest.mark.asyncio
async def test_long_columns_drop_owner_and_group_and_lead_with_question_marks():
    tree = {
        "/d": _dir("d"),
        "/d/a.txt": _file("a.txt", 42, "2025-01-15T10:30:00Z"),
    }
    readdir, stat = _make_fs_backend(tree)
    output, _ = await ls(
        [_spec("/d")],
        readdir=readdir,
        stat=stat,
        long=True,
        columns=LsColumns(
            owner=False,
            group=False,
            inode=True,
            context=True,
            time_style="long-iso",
        ),
    )
    assert (
        output.decode()
        == "total ?\n? -rw-r--r-- 1 ? 42 2025-01-15 10:30 a.txt\n"
    )
    output, _ = await ls(
        [_spec("/d")],
        readdir=readdir,
        stat=stat,
        columns=LsColumns(inode=True, context=True),
    )
    assert output.decode() == "? ? a.txt\n"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "style,expected",
    [
        ("full-iso", "2025-01-15 10:30:00.000000000 +0000"),
        ("long-iso", "2025-01-15 10:30"),
        ("iso", "2025-01-15 "),
        ("+%Y/%m/%d", "2025/01/15"),
        ("+%Y\n%H:%M", "2025"),
    ],
)
async def test_time_styles_spell_an_old_time_as_gnu_does(style, expected):
    tree = {
        "/d": _dir("d"),
        "/d/a.txt": _file("a.txt", 42, "2025-01-15T10:30:00Z"),
    }
    readdir, stat = _make_fs_backend(tree)
    output, _ = await ls(
        [_spec("/d")],
        readdir=readdir,
        stat=stat,
        long=True,
        columns=LsColumns(owner=False, group=False, time_style=style),
    )
    assert output.decode() == f"total ?\n-rw-r--r-- 1 42 {expected} a.txt\n"


@pytest.mark.asyncio
async def test_hyperlink_wraps_the_name_in_osc8():
    tree = {"/d": _dir("d"), "/d/a.txt": _file("a.txt", 1)}
    readdir, stat = _make_fs_backend(tree)
    output, _ = await ls(
        [_spec("/d")], readdir=readdir, stat=stat, hyperlink=True
    )
    assert output == b"\x1b]8;;file:///d/a.txt\x07a.txt\x1b]8;;\x07\n"


@pytest.mark.parametrize(
    "flags,sort_by,time_kind",
    [
        ({"t": True, "S": True}, LsSortBy.SIZE, LsTimeKind.MTIME),
        ({"S": True, "sort": "version"}, LsSortBy.VERSION, LsTimeKind.MTIME),
        ({"u": True}, LsSortBy.TIME, LsTimeKind.ATIME),
        ({"u": True, "args_l": True}, LsSortBy.NAME, LsTimeKind.ATIME),
        (
            {"c": True, "u": True, "time": "status"},
            LsSortBy.TIME,
            LsTimeKind.CTIME,
        ),
        ({"X": True, "U": True}, LsSortBy.NONE, LsTimeKind.MTIME),
    ],
)
def test_parse_flags_last_sort_and_time_spelling_win(
    flags, sort_by, time_kind
):
    parsed = parse_flags(flags)
    assert parsed.sort_by is sort_by
    assert parsed.time_kind is time_kind


def test_parse_flags_g_o_n_imply_long_and_shape_the_columns():
    parsed = parse_flags({"g": True, "o": True, "inode": True})
    assert parsed.long
    assert not parsed.columns.owner and not parsed.columns.group
    assert parsed.columns.inode
    assert parse_flags({"numeric_uid_gid": True}).long
    assert parse_flags({"g": True, "args_1": True}).long
    assert parse_flags({"args_l": True, "args_1": True}).long
    assert not parse_flags({"args_1": True}).long
    assert parse_flags({"block_size": "K"}).columns.block_size == BlockSize(
        1024, "K"
    )
    with pytest.raises(UsageError, match="invalid --block-size argument '0K'"):
        parse_flags({"block_size": "0K"})
    # The later of -h and --block-size wins (dict order is typed order).
    assert (
        parse_flags(
            {"block_size": "K", "human_readable": True}
        ).columns.block_size
        is None
    )
    assert parse_flags(
        {"human_readable": True, "block_size": "K"}
    ).columns.block_size == BlockSize(1024, "K")
    with pytest.raises(UsageError):
        parse_flags({"block_size": "bogus", "human_readable": True})
    assert parse_flags({"hyperlink": "always"}).hyperlink
    assert not parse_flags({"hyperlink": "auto"}).hyperlink
    assert (
        parse_flags({"time_style": "posix-long-iso"}).columns.time_style
        == "locale"
    )


# ls's argument clauses name the refused word through gnulib's quote(), so
# a byte outside 0x20-0x7e comes back escaped rather than interpolated
# raw. Rows measured against GNU coreutils 9.4 under `LC_ALL=C` with a raw
# `bytes` argv (`ls --sort=<w>`, `--time=<w>`, `--hyperlink=<w>`,
# `-l --time-style=<w>`, and `--format=<w>`, which mirage has no option
# for but which renders through the same clause). Mirrored in ls.test.ts.
QUOTED_WORDS = [
    ("xé", r"x\303\251"),
    ("x\r", r"x\r"),
    ("x\x01", r"x\001"),
    ("x\x7f", r"x\177"),
    ("x'", r"x\'"),
    ("x\\", r"x\\"),
]


@pytest.mark.parametrize("value,escaped", QUOTED_WORDS)
@pytest.mark.parametrize(
    "dest,option",
    [
        ("sort", "'--sort'"),
        ("time", "'--time'"),
        ("hyperlink", "'--hyperlink'"),
        ("time_style", "'time style'"),
    ],
)
def test_argument_clauses_quote_the_word(dest, option, value, escaped):
    with pytest.raises(UsageError) as info:
        parse_flags({dest: value})
    assert str(info.value).startswith(
        f"ls: invalid argument '{escaped}' for {option}\n"
    )


@pytest.mark.parametrize("value", ["1é", "1\x01"])
def test_block_size_clause_stays_raw(value):
    """`--block-size` is quoted but NOT escaped, which is GNU's own split.

    Measured with `ls --block-size=1é`, which reports
    `invalid suffix in --block-size argument '1é'` with the two UTF-8
    bytes intact -- so this clause must not be routed through quote()
    even though its neighbours above are.
    """
    with pytest.raises(UsageError) as info:
        parse_flags({"block_size": value, "human_readable": True})
    assert value in str(info.value)


# GNU's own `sort_args`: `none time size extension version width`, in
# that order and with no `name`. Measured on coreutils 9.4
# (`ls --sort=name` is a refusal, not name order) -- an extra word mirage
# accepted was also a word missing from the list it printed back.
def test_sort_refuses_name_the_way_gnu_does():
    with pytest.raises(UsageError) as info:
        parse_flags({"sort": "name"})
    assert str(info.value).startswith(
        "ls: invalid argument 'name' for '--sort'\n"
    )
    assert info.value.exit_code == 1


# An EMPTY ARGMATCH value is `ambiguous`, not `invalid`: gnulib's argmatch
# matches on a prefix and `""` is a prefix of every candidate. Measured on
# coreutils 9.4: `ls --sort=`, `ls --time=`, `ls --hyperlink=` are exit 1
# and `ls -l --time-style=` is exit 2, ls's own `usage (LS_FAILURE)`.
@pytest.mark.parametrize(
    "dest,option,code",
    [
        ("sort", "'--sort'", 1),
        ("time", "'--time'", 1),
        ("hyperlink", "'--hyperlink'", 1),
        ("time_style", "'time style'", 2),
    ],
)
def test_an_empty_argument_is_ambiguous(dest, option, code):
    with pytest.raises(UsageError) as info:
        parse_flags({dest: ""})
    assert str(info.value).startswith(
        f"ls: ambiguous argument '' for {option}\n"
    )
    assert info.value.exit_code == code


# gnulib's argmatch resolves an unambiguous prefix and answers the
# canonical word of the value it matched. Every row measured on coreutils
# 9.4 (`ls --sort=non`, `-l --time=acc`, `--hyperlink=n`,
# `-l --time-style=full`).
@pytest.mark.parametrize(
    "flags,attr,expected",
    [
        ({"sort": "non"}, "sort_by", LsSortBy.NONE),
        ({"sort": "n"}, "sort_by", LsSortBy.NONE),
        ({"sort": "si"}, "sort_by", LsSortBy.SIZE),
        ({"time": "a"}, "time_kind", LsTimeKind.ATIME),
        ({"time": "acc"}, "time_kind", LsTimeKind.ATIME),
        ({"time": "u"}, "time_kind", LsTimeKind.ATIME),
        ({"time": "m"}, "time_kind", LsTimeKind.MTIME),
        ({"time": "s"}, "time_kind", LsTimeKind.CTIME),
        ({"time": "b"}, "time_kind", LsTimeKind.BIRTH),
        ({"hyperlink": "al"}, "hyperlink", True),
        ({"hyperlink": "y"}, "hyperlink", True),
        ({"hyperlink": "f"}, "hyperlink", True),
        ({"hyperlink": "n"}, "hyperlink", False),
        ({"hyperlink": "au"}, "hyperlink", False),
        ({"hyperlink": "i"}, "hyperlink", False),
        ({"time_style": "full"}, "columns.time_style", "full-iso"),
        ({"time_style": "long"}, "columns.time_style", "long-iso"),
        ({"time_style": "i"}, "columns.time_style", "iso"),
        ({"time_style": "loc"}, "columns.time_style", "locale"),
        ({"time_style": "posix-full"}, "columns.time_style", "locale"),
    ],
)
def test_parse_flags_accepts_an_unambiguous_prefix(flags, attr, expected):
    assert attrgetter(attr)(parse_flags(flags)) == expected


# `ls --sort=NON`, `=NONE` and `=None` are all `invalid argument`, never
# ambiguous and never accepted: gnulib compares bytes (measured).
@pytest.mark.parametrize("value", ["NON", "NONE", "None"])
def test_prefix_matching_is_case_sensitive(value):
    with pytest.raises(UsageError) as info:
        parse_flags({"sort": value})
    assert str(info.value).startswith(
        f"ls: invalid argument '{value}' for '--sort'\n"
    )
    assert info.value.exit_code == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix", ["", "/data", "/nested/data"])
@pytest.mark.parametrize("subdir", [False, True])
@pytest.mark.parametrize("namespace", [False, True])
async def test_dot_entries_respect_mount_boundary(prefix, subdir, namespace):
    root = prefix or "/"
    directory = f"{prefix}/sub" if subdir else root
    tree = {
        root: FileStat(name="root", type=FileType.DIRECTORY, mode=0o751),
        f"{prefix}/sub": FileStat(
            name="sub", type=FileType.DIRECTORY, mode=0o750
        ),
    }
    readdir, backend_stat = _make_fs_backend(tree)
    calls = []
    namespace_calls = []

    async def stat(path, index=None):
        calls.append((path.virtual, path.vfs_path))
        assert path.virtual in tree
        assert path.vfs_path == path.virtual[len(prefix) :].strip("/")
        return await backend_stat(path, index)

    async def stat_path(path):
        namespace_calls.append(path)
        return tree.get(
            path, FileStat(name="parent", type=FileType.DIRECTORY, mode=0o700)
        )

    output, io = await ls(
        [
            PathSpec(
                virtual=directory,
                directory=directory,
                vfs_path="sub" if subdir else "",
            )
        ],
        readdir=readdir,
        stat=stat,
        long=True,
        all_files=True,
        show_dot_entries=True,
        stat_path=stat_path if namespace else None,
    )
    assert io.exit_code == 0
    assert not io.stderr
    dot_mode = "drwxr-x---" if subdir else "drwxr-x--x"
    parent_mode = (
        "drwxr-x--x"
        if subdir or not prefix
        else "drwx------"
        if namespace
        else "drwxr-xr-x"
    )
    assert f"{dot_mode} 1 - - 4096 - .\n" in output.decode()
    assert f"{parent_mode} 1 - - 4096 - ..\n" in output.decode()
    if namespace:
        parent = (
            prefix if subdir and prefix else (root.rsplit("/", 1)[0] or "/")
        )
        assert namespace_calls[-2:] == [directory, parent]
    else:
        assert calls


def _ls_view(*argv: str) -> FlagView:
    spec = SPECS["ls"]
    return FlagView(
        parse_to_kwargs(parse_command(spec, list(argv), "/", "ls")), spec=spec
    )


@pytest.mark.parametrize(
    "argv,style",
    [
        ([], LsIndicator.NONE),
        (["-F"], LsIndicator.CLASSIFY),
        (["--classify=always"], LsIndicator.CLASSIFY),
        (["--classify=never"], LsIndicator.NONE),
        (["--classify=auto"], LsIndicator.NONE),
        (["-p"], LsIndicator.SLASH),
        (["--file-type"], LsIndicator.FILE_TYPE),
        (["--indicator-style=classify"], LsIndicator.CLASSIFY),
        (["-F", "-p"], LsIndicator.SLASH),
        (["-p", "-F"], LsIndicator.CLASSIFY),
        (["--file-type", "--indicator-style=none"], LsIndicator.NONE),
    ],
)
def test_indicator_flag_takes_the_last_style(argv, style):
    # coreutils 9.7: -F, --classify[=WHEN], -p, --file-type and
    # --indicator-style all set the one style, so the last one wins; a
    # --classify that is not always has no terminal to be auto on.
    assert indicator_flag(_ls_view(*argv)) is style


@pytest.mark.parametrize(
    "argv",
    [
        ["--indicator-style=bogus"],
        ["--classify=bogus"],
        ["--indicator-style=bogus", "-F"],
    ],
)
def test_indicator_flag_refuses_a_word_gnu_does_not_know(argv):
    # GNU checks each value while it reads the options, so a bad one
    # before a good one is still refused.
    with pytest.raises(UsageError) as info:
        indicator_flag(_ls_view(*argv))
    assert str(info.value).startswith("ls: invalid argument 'bogus' for")


@pytest.mark.parametrize(
    "kind,mode,marks",
    [
        (FileType.DIRECTORY, None, ("", "/", "/", "/")),
        (FileType.SYMLINK, None, ("", "", "@", "@")),
        (FileType.FIFO, None, ("", "", "|", "|")),
        (FileType.FILE, 0o755, ("", "", "", "*")),
        (FileType.FILE, 0o644, ("", "", "", "")),
    ],
)
def test_type_indicator_marks_by_style(kind, mode, marks):
    # ls.c get_type_indicator: slash marks only directories, and only
    # classify marks an executable.
    entry = FileStat(name="x", type=kind, mode=mode)
    styles = (
        LsIndicator.NONE,
        LsIndicator.SLASH,
        LsIndicator.FILE_TYPE,
        LsIndicator.CLASSIFY,
    )
    assert tuple(type_indicator(entry, s) for s in styles) == marks


def test_type_indicator_marks_nothing_it_could_not_stat():
    assert type_indicator(None, LsIndicator.CLASSIFY) == ""
