import pytest

from mirage.commands.builtin.generic.join import (CheckOrder, JoinFlags,
                                                  parse_flags)
from mirage.core.ram.write import write_bytes
from mirage.types import MountMode, PathSpec
from mirage.vfs.ram import RAMVFS
from mirage.workspace import Workspace

GNU = [
    ("a1a2", b"1 a\n2 b\n3 c\n", b"1 x\n3 z\n4 w\n", "join -a1 -a2 a b", b"",
     0, b"1 a x\n2 b\n3 c z\n4 w\n", b""),
    ("v1v2", b"1 a\n2 b\n3 c\n", b"1 x\n3 z\n4 w\n", "join -v1 -v2 a b", b"",
     0, b"2 b\n4 w\n", b""),
    ("o_e", b"1 a\n2 b\n3 c\n", b"1 x\n3 z\n4 w\n",
     "join -a1 -a2 -e NA -o 0,1.2,2.2 a b", b"", 0,
     b"1 a x\n2 b NA\n3 c z\n4 NA w\n", b""),
    ("o_repeat", b"1 a\n2 b\n3 c\n", b"1 x\n3 z\n4 w\n",
     "join -o 1.1 -o 2.2,1.2 a b", b"", 0, b"1 x a\n3 z c\n", b""),
    ("o_trailing_comma", b"1 a\n2 b\n3 c\n", b"1 x\n3 z\n4 w\n",
     "join -o 1.1, a b", b"", 0, b"1\n3\n", b""),
    ("auto_a1a2", b"1 a b c\n2 d\n3 e f\n", b"1 x\n2 y z w\n4 q r\n",
     "join -o auto -a1 -a2 a b", b"", 0,
     b"1 a b c x\n2 d   y\n3 e f  \n4    q\n", b""),
    ("auto_e", b"1 a b c\n2 d\n3 e f\n", b"1 x\n2 y z w\n4 q r\n",
     "join -o auto -a1 -a2 -e NA a b", b"", 0,
     b"1 a b c x\n2 d NA NA y\n3 e f NA NA\n4 NA NA NA q\n", b""),
    ("t_colon_e", b"1:a::c\n2::b\n3:c\n", b"1:x:\n2:y\n:z\n",
     "join -t : -e X a b", b"", 0, b"1:a:X:c:x:X\n2:X:b:y\n", b""),
    ("t_whole_line_a", b"x y\nz w\n", b"x y\nz\n",
     "join -t '' -a1 -a2 -o 0,1.1 a b", b"", 0, b"x y x y\nz \nz w z w\n",
     b""),
    ("t_newline_o", b"x y\n", b"x y\n", "join -t $'\\n' -o 0,1.1,2.1 a b", b"",
     0, b"x y\nx y\nx y\n", b""),
    ("cr", b"1 a\r\n2 b\r\n", b"1 x\n2 y\n", "join a b", b"", 0,
     b"1 a\r x\n2 b\r y\n", b""),
    ("ws_trailing", b"1 a  \n2 b\t\n", b"1 x \n2 y\n", "join a b", b"", 0,
     b"1 a x\n2 b y\n", b""),
    ("i_toupper_order", b"A 1\n_ 2\n", b"_ y\n", "join -i a b", b"", 0,
     b"_ 2 y\n", b""),
    ("i_nonascii", b"\xc3\x89 1\n", b"\xc3\xa9 x\n", "join -i -a1 -a2 a b",
     b"", 0, b"\xc3\x89 1\n\xc3\xa9 x\n", b""),
    ("j12", b"a 1\nb 2\n", b"1 x\n2 y\n", "join -1 2 -2 1 a b", b"", 0,
     b"1 a x\n2 b y\n", b""),
    ("j_huge", b"1 a\n2 b\n3 c\n", b"1 x\n3 z\n4 w\n",
     "join -1 99999999999999999999999 -a1 a b", b"", 0, b" 1 a\n 2 b\n 3 c\n",
     b""),
    ("header_a", b"id name\n1 a\n2 b\n", b"id val\n2 y\n3 z\n",
     "join --header -a1 -a2 a b", b"", 0, b"id name val\n1 a\n2 b y\n3 z\n",
     b""),
    ("header_disorder_body", b"k h\nb 1\na 2\n", b"k g\na x\n",
     "join --header a b", b"", 1, b"k h g\n",
     b"join: a:3: is not sorted: a 2\njoin: input is not in sorted order\n"),
    ("z_newline_fieldsep", b"1\na\x002 b\x00", b"1 x\n\x002\ny\x00",
     "join -z a b", b"", 0, b"1 a x\x002 b y\x00", b""),
    ("dup_cross_mixed", b"a 1\nk 1\nk 2\nz 9\n", b"k a\nk b\nm q\n",
     "join -a1 -a2 a b", b"", 0,
     b"a 1\nk 1 a\nk 1 b\nk 2 a\nk 2 b\nm q\nz 9\n", b""),
    ("unsorted_task", b"b one\na two\n", b"a x\nb y\n", "join a b", b"", 1,
     b"b one y\n",
     b"join: a:2: is not sorted: a two\njoin: input is not in sorted order\n"),
    ("unsorted_task_nocheck", b"b one\na two\n", b"a x\nb y\n",
     "join --nocheck-order a b", b"", 0, b"b one y\n", b""),
    ("unsorted_task_check", b"b one\na two\n", b"a x\nb y\n",
     "join --check-order a b", b"", 1, b"",
     b"join: a:2: is not sorted: a two\n"),
    ("check_then_nocheck", b"b one\na two\n", b"a x\nb y\n",
     "join --check-order --nocheck-order a b", b"", 0, b"b one y\n", b""),
    ("unsorted_check_fatal_mid", b"a 1\nb 2\nd 4\nc 3\n",
     b"a x\nb y\nc z\nd w\n", "join --check-order a b", b"", 1,
     b"a 1 x\nb 2 y\n", b"join: a:4: is not sorted: c 3\n"),
    ("unsorted_both_a", b"a 1\nd 4\nc 3\nb 9\n", b"b x\ne y\nd z\nc w\n",
     "join -a1 -a2 a b", b"", 1, b"a 1\nb x\nd 4\nc 3\nb 9\ne y\nd z\nc w\n",
     b"join: a:3: is not sorted: c 3\n"
     b"join: b:3: is not sorted: d z\n"
     b"join: input is not in sorted order\n"),
    ("unsorted_before_unpair", b"b 1\na 2\nc 3\n", b"b x\nc y\nd z\n",
     "join a b", b"", 0, b"b 1 x\nc 3 y\n", b""),
    ("seen_after_advance", b"a 1\nc 2\nb\x00x 3\n", b"a x\nz q\n", "join a b",
     b"", 0, b"a 1 x\n", b""),
    ("unsorted_tail1", b"a 1\nc 3\nb 2\n", b"a x\n", "join a b", b"", 0,
     b"a 1 x\n", b""),
    ("check_tail_fatal_a1", b"a 1\nc 2\nb 3\n", b"a x\n",
     "join --check-order -a1 a b", b"", 1, b"a 1 x\nc 2\n",
     b"join: a:3: is not sorted: b 3\n"),
    ("unsorted_stdin_name", b"", b"a x\nc z\n", "join - b", b"b 1\na 2\n", 1,
     b"",
     b"join: -:2: is not sorted: a 2\njoin: input is not in sorted order\n"),
    ("astral_vs_bmp_check", b"\xef\xbc\x81 1\n\xf0\x9f\x98\x80 2\n",
     b"\xef\xbc\x81 x\n\xf0\x9f\x98\x80 y\n", "join --check-order a b", b"", 0,
     b"\xef\xbc\x81 1 x\n\xf0\x9f\x98\x80 2 y\n", b""),
    ("bytes_invalid_order", b"z 1\n\xff 2\n", b"\xff x\na q\n",
     "join -a1 -a2 a b", b"", 1, b"z 1\n\xff 2 x\na q\n",
     b"join: b:2: is not sorted: a q\njoin: input is not in sorted order\n"),
    ("nul_in_line_msg", b"a 1\nc 2\nd 3\nb\x00x 4\n", b"a x\nz q\n",
     "join a b", b"", 1, b"a 1 x\n",
     b"join: a:4: is not sorted: b\njoin: input is not in sorted order\n"),
    ("a_bad", b"1 a\n2 b\n3 c\n", b"1 x\n3 z\n4 w\n", "join -a 3 a b", b"", 1,
     b"", b"join: invalid file number: '3'\n"),
    ("f_suffix", b"1 a\n2 b\n3 c\n", b"1 x\n3 z\n4 w\n", "join -1 2x a b", b"",
     1, b"", b"join: invalid field number: '2x'\n"),
    ("j_conflict", b"1 a\n2 b\n3 c\n", b"1 x\n3 z\n4 w\n",
     "join -1 2 -j 3 a b", b"", 1, b"",
     b"join: incompatible join fields 1, 2\n"),
    ("o_empty_item", b"1 a\n2 b\n3 c\n", b"1 x\n3 z\n4 w\n",
     "join -o 1.1,,2.1 a b", b"", 1, b"",
     b"join: invalid file number in field spec: ''\n"),
    ("o_zero_dot", b"1 a\n2 b\n3 c\n", b"1 x\n3 z\n4 w\n", "join -o 0.1 a b",
     b"", 1, b"", b"join: invalid field specifier: '0.1'\n"),
    ("t_multibyte", b"1\xc3\xa9a\n", b"1\xc3\xa9x\n", "join -t é a b", b"", 1,
     b"", b"join: multi-character tab '\\303\\251'\n"),
    ("t_incompatible", b"1 a\n2 b\n3 c\n", b"1 x\n3 z\n4 w\n",
     "join -t : -t , a b", b"", 1, b"", b"join: incompatible tabs\n"),
    ("e_conflict", b"1 a\n2 b\n3 c\n", b"1 x\n3 z\n4 w\n",
     "join -e A -e B a b", b"", 1, b"",
     b"join: conflicting empty-field replacement strings\n"),
    ("missing_operand", b"1 a\n2 b\n3 c\n", b"1 x\n3 z\n4 w\n", "join a", b"",
     1, b"", b"join: missing operand after 'a'\n"
     b"Try 'join --help' for more information.\n"),
]


async def _drain(source) -> bytes:
    if source is None:
        return b""
    if isinstance(source, bytes):
        return source
    return b"".join([chunk async for chunk in source])


async def _shell(files: dict[str, bytes], cmd: str,
                 stdin: bytes) -> tuple[int, bytes, bytes]:
    ram = RAMVFS()
    for name, body in files.items():
        await write_bytes(ram.accessor, PathSpec.from_str_path(name), body)
    ws = Workspace({"/data": (ram, MountMode.WRITE)}, mode=MountMode.WRITE)
    ws._cwd = "/data"
    io = await ws.shell(cmd, stdin=stdin or None)
    return io.exit_code, await _drain(io.stdout), await _drain(io.stderr)


@pytest.mark.asyncio
@pytest.mark.parametrize("case,a,b,cmd,stdin,code,stdout,stderr",
                         GNU,
                         ids=[row[0] for row in GNU])
async def test_matches_gnu(case, a, b, cmd, stdin, code, stdout, stderr):
    """Each row is GNU join 9.7 (debian:stable-slim) run on files a and b."""
    assert await _shell({
        "/a": a,
        "/b": b
    }, cmd, stdin) == (code, stdout, stderr)


@pytest.mark.parametrize("flags,expected", [
    ({}, JoinFlags()),
    ({
        "a": "2",
        "v": "1"
    }, JoinFlags(unpairables1=True, unpairables2=True, pairables=False)),
    ({
        "j": "3"
    }, JoinFlags(field1=2, field2=2)),
    ({
        "t": ""
    }, JoinFlags(tab=b"\n", output_separator=b" ")),
    ({
        "t": "\\0"
    }, JoinFlags(tab=b"\0", output_separator=b"\0")),
    ({
        "o": "0,2.3 1.1"
    }, JoinFlags(outlist=((0, 0), (2, 2), (1, 0)))),
    ({
        "o": "auto",
        "zero_terminated": True
    }, JoinFlags(autoformat=True, eol=b"\0")),
    ({
        "nocheck_order": True
    }, JoinFlags(check_order=CheckOrder.DISABLED)),
])
def test_parse_flags(flags, expected):
    assert parse_flags(flags) == expected


@pytest.mark.asyncio
async def test_cross_mount_relay_reads_every_flag():
    one, two = RAMVFS(), RAMVFS()
    await write_bytes(one.accessor, PathSpec.from_str_path("/a"),
                      b"B 2\nx 1\n")
    await write_bytes(two.accessor, PathSpec.from_str_path("/b"),
                      b"b y\nC z\n")
    ws = Workspace(
        {
            "/data": (one, MountMode.WRITE),
            "/data2": (two, MountMode.WRITE)
        },
        mode=MountMode.WRITE)
    io = await ws.shell("join -i -j 1 -a1 -a2 -e - -o 0,1.2,2.2 "
                        "--nocheck-order /data/a /data2/b")
    assert (io.exit_code, await
            _drain(io.stdout)) == (0, b"B 2 y\nC - z\nx 1 -\n")
