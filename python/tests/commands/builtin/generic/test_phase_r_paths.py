import pytest

from mirage.commands.builtin.generic.basename import basename
from mirage.commands.builtin.generic.dirname import dirname
from mirage.commands.builtin.generic.mktemp import mktemp
from mirage.commands.builtin.generic.readlink import readlink
from mirage.types import PathSpec
from mirage.utils.key_prefix import mount_key


def _spec(original: str, prefix: str = "") -> PathSpec:
    return PathSpec(vfs_path=mount_key(original, prefix),
                    virtual=original,
                    directory=original,
                    resolved=True)


@pytest.mark.asyncio
async def test_basename_single():
    out, _ = await basename("/a/b/c.txt")
    assert out == b"c.txt\n"


@pytest.mark.asyncio
async def test_basename_suffix():
    out, _ = await basename("/a/b.txt", ".txt")
    assert out == b"b\n"


@pytest.mark.asyncio
async def test_basename_empty():
    out, _ = await basename()
    assert out == b"\n"


@pytest.mark.asyncio
async def test_dirname_single():
    out, _ = await dirname("/a/b/c.txt")
    assert out == b"/a/b\n"


@pytest.mark.asyncio
async def test_dirname_no_slash():
    out, _ = await dirname("foo")
    assert out == b".\n"


@pytest.mark.asyncio
async def test_dirname_multiple():
    out, _ = await dirname("/a/b", "/x/y/z")
    assert out == b"/a\n/x/y\n"


@pytest.mark.asyncio
async def test_readlink_simple():
    out, _ = await readlink([_spec("/a/b")])
    assert out == b"/a/b\n"


@pytest.mark.asyncio
async def test_readlink_with_prefix():
    out, _ = await readlink([_spec("/mnt/b", prefix="/mnt")])
    assert out == b"/mnt/b\n"


@pytest.mark.asyncio
async def test_readlink_normalize_with_f():
    out, _ = await readlink([_spec("/a/./b")], f=True)
    assert out == b"/a/b\n"


@pytest.mark.asyncio
async def test_readlink_no_newline():
    out, _ = await readlink([_spec("/a/b")], n=True)
    assert out == b"/a/b"


@pytest.mark.asyncio
async def test_readlink_missing_operand():
    with pytest.raises(ValueError, match="missing operand"):
        await readlink([])


@pytest.mark.asyncio
async def test_mktemp_creates_file():
    mkdir_calls: list[tuple] = []
    write_calls: list[tuple] = []

    async def mkdir_fn(path, parents=False):
        mkdir_calls.append((path, parents))

    async def write_bytes_fn(path, data):
        write_calls.append((path, data))

    out, _ = await mktemp(mkdir_fn=mkdir_fn,
                          write_bytes_fn=write_bytes_fn,
                          t=True)
    text = out.decode()
    assert text.startswith("/tmp/tmp.")
    assert text.endswith("\n")
    assert mkdir_calls == []
    assert len(write_calls) == 1
    assert write_calls[0][0].virtual == text.rstrip("\n")
    assert write_calls[0][1] == b""


@pytest.mark.asyncio
async def test_mktemp_creates_directory():
    mkdir_calls: list[tuple] = []
    write_calls: list[tuple] = []

    async def mkdir_fn(path, parents=False):
        mkdir_calls.append((path, parents))

    async def write_bytes_fn(path, data):
        write_calls.append((path, data))

    out, _ = await mktemp(mkdir_fn=mkdir_fn,
                          write_bytes_fn=write_bytes_fn,
                          d=True,
                          t=True)
    text = out.decode().rstrip("\n")
    assert [(path.virtual, parents)
            for path, parents in mkdir_calls] == [(text, False)]
    assert write_calls == []


@pytest.mark.asyncio
async def test_mktemp_custom_parent():
    mkdir_calls: list[tuple] = []

    async def mkdir_fn(path, parents=False):
        mkdir_calls.append((path, parents))

    async def write_bytes_fn(path, data):
        pass

    out, _ = await mktemp(mkdir_fn=mkdir_fn,
                          write_bytes_fn=write_bytes_fn,
                          p="/var/cache")
    assert out.decode().startswith("/var/cache/tmp.")
    assert mkdir_calls == []


@pytest.mark.asyncio
async def test_mktemp_never_creates_a_named_parent():
    # GNU creates one file or directory, never the directory it goes in:
    # a missing -p directory is ENOENT, named by the template.
    mkdir_calls: list[PathSpec] = []

    async def mkdir_fn(path):
        mkdir_calls.append(path)

    async def write_bytes_fn(path, data):
        raise FileNotFoundError(path.virtual)

    out, io = await mktemp(mkdir_fn=mkdir_fn,
                           write_bytes_fn=write_bytes_fn,
                           p="/var/cache")
    assert (out, io.exit_code, mkdir_calls) == (None, 1, [])
    assert io.stderr == (b"mktemp: failed to create file via template "
                         b"'/var/cache/tmp.XXXXXXXXXX': No such file or "
                         b"directory\n")


@pytest.mark.asyncio
async def test_mktemp_makes_only_the_fallback_tmp():
    # A workspace root starts with no /tmp, so the fallback directory is
    # made on first use, and only when nothing named another one.
    made: list[str] = []
    files: set[str] = set()

    async def mkdir_fn(path):
        made.append(path.virtual)

    async def write_bytes_fn(path, data):
        if "/tmp" not in made:
            raise FileNotFoundError(path.virtual)
        files.add(path.virtual)

    out, io = await mktemp(mkdir_fn=mkdir_fn, write_bytes_fn=write_bytes_fn)
    assert io.exit_code == 0
    assert made == ["/tmp"]
    assert files == {out.decode().rstrip("\n")}


@pytest.mark.asyncio
async def test_mktemp_pathspec_parent():
    mkdir_calls: list[tuple] = []

    async def mkdir_fn(path, parents=False):
        mkdir_calls.append((path, parents))

    async def write_bytes_fn(path, data):
        pass

    out, _ = await mktemp(mkdir_fn=mkdir_fn,
                          write_bytes_fn=write_bytes_fn,
                          p=_spec("/scratch"))
    assert out.decode().startswith("/scratch/tmp.")


@pytest.mark.asyncio
async def test_mktemp_custom_template():
    mkdir_calls: list[tuple] = []
    write_calls: list[tuple] = []

    async def mkdir_fn(path, parents=False):
        mkdir_calls.append((path, parents))

    async def write_bytes_fn(path, data):
        write_calls.append((path, data))

    out, _ = await mktemp("session_XXXXXX",
                          mkdir_fn=mkdir_fn,
                          write_bytes_fn=write_bytes_fn,
                          t=True)
    text = out.decode().rstrip("\n")
    assert text.startswith("/tmp/session_")
    assert len(text) == len("/tmp/session_") + 6


@pytest.mark.asyncio
async def test_mktemp_draws_again_when_a_name_is_taken():
    # GNU creates exclusively and tries another name, so a taken name is
    # never written over.
    probed: list[str] = []
    written: list[str] = []

    async def exists_fn(path):
        probed.append(path.virtual)
        return len(probed) == 1

    async def mkdir_fn(path):
        raise AssertionError("a file create makes no directory")

    async def write_bytes_fn(path, data):
        written.append(path.virtual)

    out, io = await mktemp("x.XXX",
                           mkdir_fn=mkdir_fn,
                           write_bytes_fn=write_bytes_fn,
                           cwd="/data",
                           exists_fn=exists_fn)
    assert io.exit_code == 0
    assert len(probed) == 2 and probed[0] != probed[1]
    assert written == [probed[1]]
    assert out == (probed[1][len("/data/"):] + "\n").encode()


@pytest.mark.asyncio
async def test_mktemp_gives_up_when_every_name_is_taken():
    written: list[str] = []

    async def exists_fn(path):
        return True

    async def write_bytes_fn(path, data):
        written.append(path.virtual)

    out, io = await mktemp("x.XXX",
                           mkdir_fn=write_bytes_fn,
                           write_bytes_fn=write_bytes_fn,
                           cwd="/data",
                           exists_fn=exists_fn)
    assert (out, io.exit_code, written) == (None, 1, [])
    assert io.stderr == (b"mktemp: failed to create file via template "
                         b"'x.XXX': File exists\n")
