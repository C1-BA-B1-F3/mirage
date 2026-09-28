import pytest

from mirage import RAMVFS, MountMode, Workspace
from mirage.io.stream import materialize
from mirage.workspace.executor.builtins.read import handle_read
from mirage.workspace.session.session import SessionState
from mirage.workspace.session.state import session_view


def make_session() -> SessionState:
    return SessionState(session_id="s1")


async def _read_ws() -> Workspace:
    ws = Workspace({"/": RAMVFS()}, mode=MountMode.WRITE)
    await ws.shell("mkdir -p /data")
    return ws


@pytest.mark.asyncio
async def test_read_invalid_option_exits_2():
    _, io, _ = await handle_read(["-q", "v"], make_session(), b"line\n")
    assert io.exit_code == 2
    assert await materialize(io.stderr) == b"read: -q: invalid option\n"


@pytest.mark.asyncio
async def test_read_dash_r_consumed_not_a_variable():
    session = make_session()
    _, io, _ = await handle_read(["-r", "v"],
                                 session,
                                 b"hello world\n",
                                 state=session_view(session))
    assert io.exit_code == 0
    assert session.env["v"] == "hello world"
    assert "-r" not in session.env


@pytest.mark.asyncio
async def test_read_defaults_to_reply():
    session = make_session()
    _, io, _ = await handle_read([],
                                 session,
                                 b"hi\n",
                                 state=session_view(session))
    assert io.exit_code == 0
    assert session.env["REPLY"] == "hi"


@pytest.mark.asyncio
async def test_read_replaces_stale_stdin_buffer():
    # A previous read's exhausted herestring buffer must not shadow a
    # new command's stdin.
    ws = await _read_ws()
    await ws.shell("read -r x <<< first")
    io = await ws.shell('read -r y <<< second\necho "y=$y"')
    assert (io.stdout or b"") == b"y=second\n"


@pytest.mark.asyncio
async def test_read_scalar_replaces_array():
    ws = await _read_ws()
    await ws.shell("a=(x y z)")
    io = await ws.shell('read -r a b <<< "one two"\necho "a=$a b=$b"')
    assert (io.stdout or b"") == b"a=one b=two\n"


# What bash printed for each line (debian:stable-slim): the commands a
# group, loop, list, function or nested shell runs read one descriptor,
# so `read` takes its own and the next command reads on from there.
READ_LEAVES_THE_REST = [
    ("printf 'a\\nb\\n' | { read x; echo \"[$x]\"; cat; }", b"[a]\nb\n"),
    ("printf 'a\\nb\\n' | sh -c 'read x; echo \"[$x]\"; cat'", b"[a]\nb\n"),
    ("printf 'a\\nb\\nc\\n' | { ( read x; echo \"[$x]\" ); cat; }",
     b"[a]\nb\nc\n"),
    ("printf 'a\\nb\\nc\\n' | { read x; read y; echo \"$x $y\"; cat; }",
     b"a b\nc\n"),
    ("printf 'a\\nb\\n' | { read -n1 x; echo \"[$x]\"; cat; }", b"[a]\n\nb\n"),
    ("printf 'abc\\ndef\\n' | { read -N2 x; echo \"[$x]\"; cat; }",
     b"[ab]\nc\ndef\n"),
    ("printf 'a:b\\nc\\n' | { read -d: x; echo \"[$x]\"; cat; }",
     b"[a]\nb\nc\n"),
    ("printf 'a\\nb\\n' | { cat; read x; echo \"[$x]\"; }", b"a\nb\n[]\n"),
    ("printf 'a\\nb\\nc\\n' | while read x; do echo \"[$x]\"; cat; done",
     b"[a]\nb\nc\n"),
    ("printf 'a\\nb\\nc\\n' | { read x; for i in 1 2; do read y; "
     "echo \"[$y]\"; done; }", b"[b]\n[c]\n"),
    ("f() { read x; echo \"[$x]\"; }; printf 'a\\nb\\nc\\n' | { f; f; cat; }",
     b"[a]\n[b]\nc\n"),
    ("printf 'a\\nb\\nc\\n' | { eval 'read x'; echo \"[$x]\"; cat; }",
     b"[a]\nb\nc\n"),
    ("printf 'read y; echo \"[$y]\"\\n' > /data/s.sh; "
     "printf 'a\\nb\\n' | { source /data/s.sh; cat; }", b"[a]\nb\n"),
    ("printf 'a\\nb\\nc\\n' | { read x && cat; }", b"b\nc\n"),
    ("printf 'a\\nb\\n' | case x in x) read a; read b; echo \"$a$b\";; esac",
     b"ab\n"),
    ("printf 'a\\nb\\nc\\n' | { read x; mapfile -t r; "
     "echo \"[$x] ${#r[@]}\"; }", b"[a] 2\n"),
    ("printf '1\\n2\\n' | { select v in p q; do echo \"[$v]\"; break; done; "
     "cat; }", b"[p]\n2\n"),
    ("printf 'a\\nb\\nc\\n' | { read x; xargs echo; }", b"b c\n"),
    ("printf 'a\\nb\\n' > /data/f; { read x; echo \"[$x]\"; cat; } < /data/f",
     b"[a]\nb\n"),
    ("{ read x; echo \"[$x]\"; cat; } <<< $'a\\nb'", b"[a]\nb\n"),
    ("printf 'a\\nb\\nc\\n' > /data/f; exec < /data/f; read x; read y; "
     "echo \"[$x][$y]\"", b"[a][b]\n"),
    ("read x <<< ''; read y <<< ''; echo \"$? [$y]\"", b"0 []\n"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("line, expected", READ_LEAVES_THE_REST)
async def test_read_leaves_the_rest_for_the_next_command(
        line: str, expected: bytes):
    ws = await _read_ws()
    io = await ws.shell(line)
    assert await materialize(io.stdout) == expected
    assert io.exit_code == 0
