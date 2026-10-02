import gzip

import pytest

from mirage.commands.builtin.generic.decompress import (
    decompress_inputs,
    gzip_suffix,
    suffix_refusal,
)
from mirage.io.types import materialize
from mirage.types import FileStat, FileType, PathSpec

HELLO = gzip.compress(b"hello", mtime=0)


def _files(files: dict[str, bytes]):
    reads: list[str] = []

    async def read(path):
        reads.append(path.virtual)
        if path.virtual.endswith("/dir"):
            raise IsADirectoryError(path.virtual)
        if path.virtual not in files:
            raise FileNotFoundError(path.virtual)
        return files[path.virtual]

    async def write(path, data):
        files[path.virtual] = data

    async def unlink(path):
        del files[path.virtual]

    async def stat(path):
        if path.virtual not in files:
            raise FileNotFoundError(path.virtual)
        return FileStat(name=path.virtual, type=FileType.FILE)

    return reads, dict(read=read, write=write, unlink=unlink, stat=stat)


def _typed(virtual: str, typed: str) -> PathSpec:
    return PathSpec(
        virtual=virtual,
        directory=virtual[: virtual.rfind("/") + 1],
        vfs_path=virtual.strip("/"),
        raw_path=typed,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("suffix", [None, b"x", b"\x1f"])
async def test_fatal_input_never_reads_later_operands_or_stdin(suffix):
    reads = []

    async def read(path):
        reads.append(path.virtual)
        return b"" if suffix is None else gzip.compress(b"hello") + suffix

    async def stdin():
        reads.append("stdin")
        yield gzip.compress(b"hello")

    paths = [
        PathSpec.from_str_path(p) for p in ("/a/bad.gz", "/b/missing.gz", "-")
    ]
    body, io = await decompress_inputs(
        paths, read=read, stdin=stdin(), to_stdout=True
    )
    assert await materialize(body) == (b"" if suffix is None else b"hello")
    assert reads == ["/a/bad.gz"]
    assert io.exit_code == 1
    assert io.stderr == b"\ngzip: /a/bad.gz: unexpected end of file\n"


@pytest.mark.asyncio
async def test_trailing_warning_keeps_in_place_output_and_continues():
    files = {"/data/a.gz": HELLO + b"junk", "/data/b.gz": gzip.compress(b"w")}
    _, ops = _files(files)
    paths = [PathSpec.from_str_path(p) for p in list(files)]
    _, io = await decompress_inputs(paths, **ops)
    assert files == {"/data/a": b"hello", "/data/b": b"w"}
    assert io.exit_code == 2
    assert io.stderr == (
        b"\ngzip: /data/a.gz: decompression OK, trailing garbage ignored\n"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "suffix,tried,shown",
    [
        (".gz", ["/d/x", "/d/x.gz", "/d/x.z", "/d/x-z", "/d/x.Z"], "x.gz"),
        (
            ".y",
            ["/d/x", "/d/x.y", "/d/x.gz", "/d/x.z", "/d/x-z", "/d/x.Z"],
            "x.y",
        ),
    ],
)
async def test_a_missing_name_is_retried_with_each_suffix(
    suffix, tried, shown
):
    # gzip 1.13 opens the name, then the name with each suffix, and
    # names the -S one when every open misses.
    reads, ops = _files({})
    body, io = await decompress_inputs(
        [_typed("/d/x", "x")], to_stdout=True, suffix=suffix, **ops
    )
    assert await materialize(body) == b""
    assert reads == tried
    assert (io.exit_code, io.stderr) == (
        1,
        f"gzip: {shown}: No such file or directory\n".encode(),
    )


@pytest.mark.asyncio
async def test_a_name_with_a_known_suffix_is_not_retried():
    reads, ops = _files({})
    _, io = await decompress_inputs([_typed("/d/x.GZ", "x.GZ")], **ops)
    assert reads == ["/d/x.GZ"]
    assert io.stderr == b"gzip: x.GZ: No such file or directory\n"


@pytest.mark.asyncio
async def test_the_empty_name_tries_the_suffixes_themselves():
    reads, ops = _files({})
    empty = PathSpec(
        virtual="/d",
        directory="/",
        vfs_path="d",
        raw_path="",
        walk_error="ENOENT",
    )

    async def read(path):
        reads.append(path.raw_path)
        raise FileNotFoundError(path.virtual)

    ops["read"] = read
    _, io = await decompress_inputs([empty], **ops)
    assert reads == ["", ".gz", ".z", "-z", ".Z"]
    assert io.stderr == b"gzip: .gz: No such file or directory\n"


@pytest.mark.asyncio
async def test_quiet_silences_a_directory_warning_but_keeps_exit_2():
    _, ops = _files({})
    body, io = await decompress_inputs(
        [PathSpec.from_str_path("/d/dir")], to_stdout=True, quiet=True, **ops
    )
    assert await materialize(body) == b""
    assert (io.stderr, io.exit_code) == (None, 2)


@pytest.mark.asyncio
async def test_an_output_already_there_outranks_a_corrupt_body():
    # gzip checks the output once the header reads, before the body.
    files = {"/d/e.gz": HELLO[:-3], "/d/e": b"old"}
    _, ops = _files(files)
    _, io = await decompress_inputs([PathSpec.from_str_path("/d/e.gz")], **ops)
    assert io.stderr == b"gzip: /d/e already exists;\tnot overwritten\n"
    assert io.exit_code == 2


@pytest.mark.asyncio
async def test_a_bad_header_outranks_an_output_already_there():
    files = {"/d/e.gz": b"plain\n", "/d/e": b"old"}
    _, ops = _files(files)
    _, io = await decompress_inputs([PathSpec.from_str_path("/d/e.gz")], **ops)
    assert io.stderr == b"\ngzip: /d/e.gz: not in gzip format\n"
    assert io.exit_code == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "data,out",
    [
        (b"", b""),
        (b"\x1f", b"\x1f"),
        (HELLO + b"\0\0", b"hello\0\0"),
    ],
)
async def test_force_copies_what_is_not_gzip_to_stdout(data, out):
    _, ops = _files({"/d/f": data})
    body, io = await decompress_inputs(
        [PathSpec.from_str_path("/d/f")], to_stdout=True, force=True, **ops
    )
    assert (await materialize(body), io.exit_code, io.stderr) == (out, 0, None)


@pytest.mark.asyncio
async def test_stdin_that_is_not_gzip_ends_the_run():
    reads, ops = _files({"/d/x.gz": HELLO})

    async def stdin():
        yield b"plain"

    body, io = await decompress_inputs(
        [PathSpec.from_str_path(p) for p in ("-", "/d/x.gz")],
        stdin=stdin(),
        to_stdout=True,
        **ops,
    )
    assert await materialize(body) == b""
    assert reads == []
    assert (io.exit_code, io.stderr) == (
        1,
        b"\ngzip: stdin: not in gzip format\n",
    )


@pytest.mark.asyncio
async def test_quiet_keeps_the_trailing_garbage_exit_code():
    _, ops = _files({"/d/f.gz": HELLO + b"junk"})
    body, io = await decompress_inputs(
        [PathSpec.from_str_path("/d/f.gz")], to_stdout=True, quiet=True, **ops
    )
    assert (await materialize(body), io.exit_code, io.stderr) == (
        b"hello",
        2,
        None,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("suffix", ["", "." + "a" * 30])
async def test_an_unusable_suffix_is_refused_before_any_input(suffix):
    reads, ops = _files({"/d/x.gz": HELLO})
    _, io = await decompress_inputs(
        [PathSpec.from_str_path("/d/x.gz")], suffix=suffix, **ops
    )
    assert reads == []
    assert (io.exit_code, io.stderr) == (
        1,
        f"gzip: invalid suffix '{suffix}'\n".encode(),
    )


@pytest.mark.parametrize(
    "name,suffix,found",
    [
        ("a.gz", ".gz", ".gz"),
        ("a.GZ", ".gz", ".GZ"),
        ("a.Tgz", ".gz", ".Tgz"),
        ("a_z", ".gz", "_z"),
        ("a-GZ", ".gz", "-GZ"),
        ("a.txt", ".gz", None),
        (".gz", ".gz", None),
        ("d/.gz", ".gz", None),
        ("a.xy", ".XY", ".xy"),
        ("a.gz", "z", ".gz"),
        ("az", "z", "z"),
    ],
)
def test_gzip_suffix_reads_gzips_suffix_table(name, suffix, found):
    assert gzip_suffix(name, suffix) == found


@pytest.mark.parametrize(
    "suffix,refused",
    [
        (".gz", False),
        ("", True),
        ("." + "a" * 29, False),
        ("." + "a" * 30, True),
    ],
)
def test_suffix_refusal_takes_one_to_thirty_bytes(suffix, refused):
    assert (suffix_refusal(suffix) is not None) is refused
