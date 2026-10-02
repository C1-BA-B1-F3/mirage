import pytest

from mirage.commands.builtin.generic.sed import sed
from mirage.types import PathSpec


def _spec(path: str) -> PathSpec:
    return PathSpec(
        vfs_path=(path).strip("/"), virtual=path, directory=path, resolved=True
    )


def _make_backend(files: dict[str, bytes]):
    store = dict(files)

    async def read_bytes(path):
        spec = (
            path
            if isinstance(path, PathSpec)
            else PathSpec(
                vfs_path=(path).strip("/"), virtual=path, directory=path
            )
        )
        if spec.virtual not in store:
            raise FileNotFoundError(spec.virtual)
        return store[spec.virtual]

    async def write_bytes(path, data):
        spec = (
            path
            if isinstance(path, PathSpec)
            else PathSpec(
                vfs_path=(path).strip("/"), virtual=path, directory=path
            )
        )
        store[spec.virtual] = data

    return read_bytes, write_bytes, store


@pytest.mark.asyncio
async def test_sed_p_flag_prints_substituted_line_twice():
    rb, wb, _ = _make_backend({})
    output, _ = await sed(
        [], "s/hi/HI/p", read_bytes=rb, write_bytes=wb, stdin=b"hi\nbye\n"
    )
    assert output == b"HI\nHI\nbye\n"


@pytest.mark.asyncio
async def test_sed_p_flag_under_suppress_prints_only_substituted():
    rb, wb, _ = _make_backend({})
    output, _ = await sed(
        [],
        "s/hi/HI/p",
        read_bytes=rb,
        write_bytes=wb,
        stdin=b"hi\nbye\n",
        suppress=True,
    )
    assert output == b"HI\n"


@pytest.mark.asyncio
async def test_sed_y_mismatched_lengths_refused():
    rb, wb, _ = _make_backend({})
    output, io = await sed(
        [], "y/ab/x/", read_bytes=rb, write_bytes=wb, stdin=b"a\n"
    )
    assert output is None
    assert io.exit_code == 1
    assert io.stderr == (
        b"sed: -e expression #1, char 7: strings for `y' "
        b"command are different lengths\n"
    )


@pytest.mark.asyncio
async def test_sed_bre_plus_is_literal():
    rb, wb, _ = _make_backend({})
    output, _ = await sed(
        [], "s/a+/X/", read_bytes=rb, write_bytes=wb, stdin=b"a+b\n"
    )
    assert output == b"Xb\n"


@pytest.mark.asyncio
async def test_sed_inplace_transliterate_writes_file():
    rb, wb, store = _make_backend({"/a.txt": b"one\ntwo\n"})
    output, _ = await sed(
        [_spec("/a.txt")],
        "y/o/0/",
        read_bytes=rb,
        write_bytes=wb,
        in_place=True,
    )
    assert output is None
    assert store["/a.txt"] == b"0ne\ntw0\n"


@pytest.mark.asyncio
async def test_sed_inplace_suppress_print_rewrites_same_content():
    rb, wb, store = _make_backend({"/a.txt": b"one\ntwo\n"})
    output, _ = await sed(
        [_spec("/a.txt")],
        "p",
        read_bytes=rb,
        write_bytes=wb,
        in_place=True,
        suppress=True,
    )
    assert output is None
    assert store["/a.txt"] == b"one\ntwo\n"


@pytest.mark.asyncio
async def test_sed_address_keeps_bre_escapes():
    rb, wb, _ = _make_backend({})
    output, _ = await sed(
        [],
        r"/a\+b/d",
        read_bytes=rb,
        write_bytes=wb,
        stdin=b"x\na+b\naab\ny\n",
    )
    assert output == b"x\na+b\ny\n"


@pytest.mark.asyncio
async def test_sed_address_range_with_escaped_delimiters():
    rb, wb, _ = _make_backend({})
    output, _ = await sed(
        [],
        r"/a\/b/,/c\/d/d",
        read_bytes=rb,
        write_bytes=wb,
        stdin=b"x\na/b\nmid\nc/d\ny\n",
    )
    assert output == b"x\ny\n"


@pytest.mark.asyncio
async def test_sed_unterminated_address_refused():
    rb, wb, _ = _make_backend({})
    _, io = await sed(
        [], "/a\\/b", read_bytes=rb, write_bytes=wb, stdin=b"x\n"
    )
    assert io.exit_code == 1
    assert io.stderr == (
        b"sed: -e expression #1, char 5: unterminated address regex\n"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "script,separate,out",
    [
        ("p", False, b"one\ntwo\nthree\n"),
        ("n;p", True, b"two\n"),
    ],
)
async def test_sed_reads_nothing_after_a_directory(script, separate, out):
    rb, wb, _ = _make_backend({"/f": b"one\ntwo\nthree\n", "/g": b"L1\nL2\n"})
    reads: list[str] = []

    async def read(path):
        reads.append(path.virtual)
        if path.virtual == "/d":
            raise IsADirectoryError(21, "Is a directory", "/d")
        return await rb(path)

    output, io = await sed(
        [_spec("/f"), _spec("/d"), _spec("/g")],
        script,
        read_bytes=read,
        write_bytes=wb,
        suppress=True,
        separate=separate,
    )
    assert output == out
    assert io.exit_code == 4
    assert reads == ["/f", "/d"]
