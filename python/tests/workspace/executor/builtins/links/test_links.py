import pytest

from mirage.policy import Action, Deny, OpsContext, Policy
from mirage.types import MountMode, PathSpec
from mirage.vfs.ram import RAMVFS
from mirage.workspace import Workspace
from mirage.workspace.executor.builtins.links import (accepts_line,
                                                      follow_parent,
                                                      follow_paths, link_flags,
                                                      prepare_mv, settle_moves)


def _ws() -> Workspace:
    return Workspace({"/data": (RAMVFS(), MountMode.WRITE)},
                     mode=MountMode.WRITE)


def test_link_flags_reads_the_known_letters():
    assert link_flags(["-sf", PathSpec.from_str_path("/data/a")],
                      "sfnvrT") == {"s", "f"}
    assert link_flags([PathSpec.from_str_path("/data/a")], "sfnvrT") == set()


@pytest.mark.asyncio
async def test_follow_parent_resolves_every_component_but_the_last():
    ws = _ws()
    await ws.shell("mkdir -p /data/real; ln -s /data/real /data/dlink")
    ns = ws.namespace
    assert follow_parent(ns, "/data/dlink/f2") == "/data/real/f2"
    assert follow_parent(ns, "/data/dlink") == "/data/dlink"


@pytest.mark.asyncio
async def test_follow_paths_follows_the_last_component_only_when_asked():
    ws = _ws()
    await ws.shell("mkdir -p /data/real; ln -s /data/real /data/dlink")
    ns = ws.namespace
    item = PathSpec.from_str_path("/data/dlink")
    kept = follow_paths(ns, [item], follow_last=False)
    assert kept[0].virtual == "/data/dlink"
    followed = follow_paths(ns, [item], follow_last=True)
    assert followed[0].virtual == "/data/real"
    slashed = follow_paths(ns, [PathSpec.from_str_path("/data/dlink/")],
                           follow_last=False)
    assert slashed[0].virtual == "/data/real/"


@pytest.mark.asyncio
async def test_follow_paths_refuses_a_loop_per_operand():
    # A loop no longer fails the whole line: the operand stays as typed
    # with the walk's verdict on it, and its neighbours still resolve.
    ws = _ws()
    await ws.shell("mkdir -p /data/real; ln -s /data/real /data/dlink; "
                   "ln -s /data/l2 /data/l1; ln -s /data/l1 /data/l2")
    ns = ws.namespace
    loop, link = follow_paths(ns, [
        PathSpec.from_str_path("/data/l1"),
        PathSpec.from_str_path("/data/dlink")
    ])
    assert (loop.virtual, loop.walk_error) == ("/data/l1", "ELOOP")
    assert (link.virtual, link.walk_error) == ("/data/real", None)
    under = follow_paths(ns, [PathSpec.from_str_path("/data/l1/x")],
                         follow_last=False)
    assert under[0].walk_error == "ELOOP"
    # lstat semantics never reach the looping name itself.
    kept = follow_paths(ns, [PathSpec.from_str_path("/data/l1")],
                        follow_last=False)
    assert kept[0].walk_error is None


@pytest.mark.asyncio
async def test_mv_onto_a_loop_replaces_the_link():
    # stat(2) of the destination fails ELOOP, which GNU mv reads as "not
    # a directory": the rename lands on the link's own name.
    ws = _ws()
    await ws.shell("echo b > /data/b.txt; "
                   "ln -s /data/l2 /data/l1; ln -s /data/l1 /data/l2")
    r = await ws.shell("mv /data/b.txt /data/l1")
    assert r.exit_code == 0
    assert not ws.namespace.is_link("/data/l1")
    assert (await ws.shell("cat /data/l1")).stdout == b"b\n"


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["missing", "a.txt", "l1"])
async def test_mv_symlink_onto_a_loop_replaces_destination(source):
    ws = _ws()
    await ws.shell("echo a > /data/a.txt; "
                   "ln -s l2 /data/l1; ln -s l1 /data/l2; "
                   f"ln -s {source} /data/src")
    result = await ws.shell("mv /data/src /data/l1")
    assert result.exit_code == 0
    assert not result.stderr
    assert not ws.namespace.is_link("/data/src")
    assert (await
            ws.shell("readlink /data/l1")).stdout == f"{source}\n".encode()


def test_accepts_line_refuses_what_the_command_layer_would():
    good = [PathSpec.from_str_path("/data/dlink")]
    assert accepts_line("rm", ("/data/dlink", ), good, "/data")
    assert not accepts_line("rm", ("--bogus", "/data/dlink"), good, "/data")
    two = [
        PathSpec.from_str_path("/data/a"),
        PathSpec.from_str_path("/data/b")
    ]
    assert not accepts_line("unlink", ("/data/a", "/data/b"), two, "/data")


class PinLinks(Policy):

    async def pre_ops(self, ctx: OpsContext) -> Action | None:
        if ctx.op == "unlink" and ctx.path.virtual.endswith(".pinned"):
            return Deny("pinned")
        return None


@pytest.mark.asyncio
async def test_ln_f_refuses_the_same_file_before_removing_it():
    # Pinned on coreutils 9.7: `ln -sf a a` and `ln -f a a` are refused
    # and the file survives, spelled as typed on both sides; a backup
    # waives the check; a destination that is not there is not the
    # same file and becomes a self-loop, as in GNU.
    ws = _ws()
    await ws.shell("printf hi > /data/a.txt")
    for line, wording in (
        ("ln -sf /data/a.txt /data/a.txt", "'/data/a.txt' and '/data/a.txt'"),
        ("ln -f /data/a.txt /data/a.txt", "'/data/a.txt' and '/data/a.txt'"),
        ("cd /data && ln -sf a.txt ./a.txt", "'a.txt' and './a.txt'"),
        ("cd /data && ln -sfT a.txt a.txt", "'a.txt' and 'a.txt'"),
    ):
        r = await ws.shell(line)
        assert r.exit_code == 1
        assert r.stderr == f"ln: {wording} are the same file\n".encode()
        assert (await ws.shell("cat /data/a.txt")).stdout == b"hi"
        assert not ws.namespace.is_link("/data/a.txt")
    r = await ws.shell("ln -sfb /data/a.txt /data/a.txt")
    assert r.exit_code == 0
    assert (await ws.shell("cat /data/a.txt~")).stdout == b"hi"
    assert ws.namespace.readlink("/data/a.txt") == "/data/a.txt"
    r = await ws.shell("ln -sf /data/nope /data/nope")
    assert r.exit_code == 0
    assert ws.namespace.readlink("/data/nope") == "/data/nope"


@pytest.mark.asyncio
async def test_ln_backup_refuses_a_directory_destination():
    # Pinned on coreutils 9.7: a backup moves a file aside, never a
    # directory, so `ln -bT a d` is refused with the directory intact
    # where mirage used to rename the whole tree to `d~`; a symlink
    # standing at the name is what -T names and is backed up; without
    # -T the directory is where the link goes.
    ws = _ws()
    await ws.shell("mkdir -p /data/d; printf hi > /data/a.txt")
    for line in (
            "ln -sbT /data/a.txt /data/d",
            "ln -bT /data/a.txt /data/d",
            "ln -sfbT /data/a.txt /data/d",
            "ln -s --backup=numbered -T /data/a.txt /data/d",
    ):
        r = await ws.shell(line)
        assert r.exit_code == 1
        assert r.stderr == b"ln: /data/d: cannot overwrite directory\n"
        assert (await ws.shell("ls /data")).stdout == b"a.txt\nd\n"
        assert not ws.namespace.is_link("/data/d")
    r = await ws.shell("ln -sb /data/a.txt /data/d")
    assert r.exit_code == 0
    assert ws.namespace.readlink("/data/d/a.txt") == "/data/a.txt"
    await ws.shell("ln -s /data/d /data/lk")
    r = await ws.shell("ln -sbT /data/a.txt /data/lk")
    assert r.exit_code == 0
    assert ws.namespace.readlink("/data/lk") == "/data/a.txt"
    assert ws.namespace.readlink("/data/lk~") == "/data/d"


class SealReads(Policy):

    async def pre_ops(self, ctx: OpsContext) -> Action | None:
        if ctx.op == "read" and ctx.path.virtual.endswith(".sealed"):
            return Deny("sealed")
        return None


@pytest.mark.asyncio
async def test_ln_keeps_going_after_a_source_it_cannot_read():
    # GNU names the source it cannot reach and links the rest, exit 1.
    # mirage's hard link is a byte copy, so a read the stat did not
    # foresee (a policy deny here) is that refusal, not an abort.
    ws = Workspace({"/data": (RAMVFS(), MountMode.WRITE)},
                   mode=MountMode.WRITE,
                   policies=[SealReads()])
    await ws.shell("mkdir /data/d; printf a > /data/a.sealed; "
                   "printf b > /data/b.txt")
    r = await ws.shell("ln /data/a.sealed /data/b.txt /data/d")
    assert r.exit_code == 1
    assert r.stderr == (b"ln: failed to access '/data/a.sealed': "
                        b"Permission denied\n")
    assert (await
            ws.shell("ls /data/d; cat /data/d/b.txt")).stdout == b"b.txt\nb"


@pytest.mark.asyncio
async def test_rm_of_a_link_goes_through_the_door():
    # The strip used to write the node table directly, so a pre_ops
    # policy protecting a link never fired for `rm` while it fired for
    # every other door (the FUSE unlink hole, one tier up). The mount is
    # writable, so only the policy can be what refuses.
    ws = Workspace({"/data": (RAMVFS(), MountMode.WRITE)},
                   mode=MountMode.WRITE,
                   policies=[PinLinks()])
    await ws.shell("echo b > /data/f.txt")
    await ws.shell("ln -s f.txt /data/lk.pinned")
    r = await ws.shell("rm /data/lk.pinned")
    assert r.exit_code == 1
    assert r.stderr == (b"rm: cannot remove '/data/lk.pinned': "
                        b"Permission denied\n")
    assert ws.namespace.is_link("/data/lk.pinned")


@pytest.mark.asyncio
async def test_rm_of_a_link_on_read_turf_answers_like_a_backend_file():
    # Byte for byte what `rm` of a backend file on the same grant
    # answers, because one grant must not describe itself two ways
    # depending on whether the name it stopped was a link.
    ws = _ws()
    await ws.shell("echo b > /data/f.txt; ln -s f.txt /data/lk")
    ws.create_session("agent", mounts={"/data/": "read"})
    r = await ws.shell("rm /data/lk", session_id="agent")
    assert r.exit_code == 1
    assert r.stderr == (b"rm: cannot remove '/data/lk': "
                        b"Read-only file system\n")
    assert ws.namespace.is_link("/data/lk")


@pytest.mark.asyncio
async def test_ln_and_mv_answer_a_read_grant_per_operand():
    # Same rule for the other two verbs that write the node table: `ln`
    # answers as `touch` does on a read-only mount, and `mv` as `mv` of
    # a backend file does, in GNU's per-operand voice.
    ws = _ws()
    await ws.shell("echo b > /data/f.txt; ln -s f.txt /data/lk")
    ws.create_session("agent", mounts={"/data/": "read"})
    ln = await ws.shell("ln -s f.txt /data/lk2", session_id="agent")
    mv = await ws.shell("mv /data/lk /data/lk3", session_id="agent")
    assert ln.exit_code == 1
    assert ln.stderr == (b"ln: failed to create symbolic link '/data/lk2': "
                         b"Read-only file system\n")
    assert mv.exit_code == 1
    assert mv.stderr == (b"mv: cannot move '/data/lk' to '/data/lk3': "
                         b"Read-only file system\n")
    assert ws.namespace.readlink("/data/lk") == "f.txt"


@pytest.mark.asyncio
async def test_a_refused_link_operand_keeps_the_rest_going():
    # GNU rm reports the operand it could not remove and removes the
    # others; the backend half of the line still runs and the exit code
    # says something failed.
    ws = Workspace({"/data": (RAMVFS(), MountMode.WRITE)},
                   mode=MountMode.WRITE,
                   policies=[PinLinks()])
    await ws.shell("echo b > /data/f.txt")
    await ws.shell("ln -s f.txt /data/lk.pinned; ln -s f.txt /data/lk")
    r = await ws.shell("rm /data/lk.pinned /data/lk /data/f.txt")
    assert r.exit_code == 1
    assert r.stderr == (b"rm: cannot remove '/data/lk.pinned': "
                        b"Permission denied\n")
    assert ws.namespace.is_link("/data/lk.pinned")
    assert not ws.namespace.is_link("/data/lk")
    assert (await ws.shell("test -e /data/f.txt; echo $?")).stdout == b"1\n"


@pytest.mark.asyncio
async def test_rm_f_still_reports_a_mode_refusal():
    # GNU -f silences only the absent; EROFS is not ENOENT.
    ws = _ws()
    await ws.shell("echo b > /data/f.txt; ln -s f.txt /data/lk")
    ws.create_session("agent", mounts={"/data/": "read"})
    r = await ws.shell("rm -f /data/lk", session_id="agent")
    assert r.exit_code == 1
    assert r.stderr == (b"rm: cannot remove '/data/lk': "
                        b"Read-only file system\n")


@pytest.mark.asyncio
async def test_rm_f_silences_a_hidden_link():
    # A hidden link answers ENOENT (the no-name-leak rule), which is
    # exactly what -f silences; without -f the miss is reported.
    ws = _ws()
    await ws.shell("echo b > /data/f.txt; ln -s f.txt /data/lk.sec")
    ws.create_session("agent", profile={"paths": {"hide": ["/data/lk.sec"]}})
    silent = await ws.shell("rm -f /data/lk.sec", session_id="agent")
    loud = await ws.shell("rm /data/lk.sec", session_id="agent")
    assert silent.exit_code == 0
    assert silent.stderr in (None, b"")
    assert loud.exit_code == 1
    assert loud.stderr == (b"rm: cannot remove '/data/lk.sec': "
                           b"No such file or directory\n")
    assert ws.namespace.is_link("/data/lk.sec")


@pytest.mark.asyncio
async def test_every_refused_operand_speaks_in_one_voice():
    # GNU reports each operand it could not remove, so a read grant is
    # one line per operand -- a link the node table refuses and a
    # backend file the op door refuses say the same thing.
    ws = _ws()
    await ws.shell("echo b > /data/f.txt")
    await ws.shell("ln -s f.txt /data/l1; ln -s f.txt /data/l2")
    ws.create_session("agent", mounts={"/data/": "read"})
    for operands in (["l1", "l2"], ["l1", "f.txt"], ["l1", "l2", "f.txt"]):
        line = "rm " + " ".join(f"/data/{name}" for name in operands)
        r = await ws.shell(line, session_id="agent")
        assert r.exit_code == 1, line
        assert r.stderr == b"".join(
            f"rm: cannot remove '/data/{name}': Read-only file system\n".
            encode() for name in operands), line
    assert ws.namespace.is_link("/data/l1")
    assert ws.namespace.is_link("/data/l2")


@pytest.mark.asyncio
async def test_prepare_mv_hands_back_the_pair_whatever_the_table_holds():
    # Gated on the source carrying overlay attrs, the pair was withheld
    # for a directory whose own node is empty, and every link below it
    # stayed at the emptied name: readable nowhere, since the backend
    # holds no entry for a link at all.
    ws = _ws()
    await ws.shell("mkdir -p /data/d; printf 't\\n' > /data/t")
    await ws.shell("ln -s /data/t /data/d/link")
    _items, moves, early, errors = await prepare_mv(
        ws.namespace, ws.dispatch, [
            PathSpec.from_str_path("/data/d"),
            PathSpec.from_str_path("/data/moved")
        ], ("/data/d", "/data/moved"), "/")
    assert early is None
    assert errors == []
    assert moves == [("/data/d", "/data/moved", False)]


@pytest.mark.asyncio
async def test_prepare_mv_reads_the_destination_off_the_parsed_line():
    # -T names the destination outright, so the basename is not appended
    # to it, and -t makes every positional a source and the flag's value
    # the directory they land in, whatever the order of the words.
    ws = _ws()
    await ws.shell("mkdir -p /data/dst; printf 'a\\n' > /data/a")
    pair = [
        PathSpec.from_str_path("/data/a"),
        PathSpec.from_str_path("/data/dst")
    ]
    _items, into, _early, _errors = await prepare_mv(ws.namespace, ws.dispatch,
                                                     pair,
                                                     ("/data/a", "/data/dst"),
                                                     "/")
    assert into == [("/data/a", "/data/dst/a", False)]
    _items, onto, _early, _errors = await prepare_mv(
        ws.namespace, ws.dispatch, pair, ("-T", "/data/a", "/data/dst"), "/")
    assert onto == [("/data/a", "/data/dst", True)]
    _items, target_dir, _early, _errors = await prepare_mv(
        ws.namespace, ws.dispatch, pair, ("-t", "/data/dst", "/data/a"), "/")
    assert target_dir == [("/data/a", "/data/dst/a", False)]


@pytest.mark.asyncio
async def test_prepare_mv_follows_a_linked_destination_for_many_sources():
    # GNU stats the destination of `mv a b dlink` through the link, so the
    # generic mv is handed the directory it names (coreutils 9.7), and
    # each source lands inside it.
    ws = _ws()
    await ws.shell("mkdir -p /data/dst; printf a > /data/a; printf b > /data/b"
                   )
    await ws.shell("ln -s /data/dst /data/dlink")
    items: list[str | PathSpec] = [
        PathSpec.from_str_path("/data/a"),
        PathSpec.from_str_path("/data/b"),
        PathSpec(vfs_path="dlink",
                 virtual="/data/dlink",
                 directory="/data/",
                 raw_path="dlink")
    ]
    rewritten, moves, early, errors = await prepare_mv(ws.namespace,
                                                       ws.dispatch, items,
                                                       ("a", "b", "dlink"),
                                                       "/data")
    assert early is None and errors == []
    dst = rewritten[-1]
    assert isinstance(dst, PathSpec)
    assert (dst.virtual, dst.raw_path) == ("/data/dst", "dlink")
    assert moves == [("/data/a", "/data/dst/a", False),
                     ("/data/b", "/data/dst/b", False)]


@pytest.mark.asyncio
async def test_prepare_mv_renames_a_link_source_among_many():
    # A link has no backend entry for the generic mv to move, so a
    # several-source mv lost it (`mv: cannot stat 'l'`); the namespace
    # renames it into the directory and the rest go to the backend.
    ws = _ws()
    await ws.shell("mkdir -p /data/dst; printf a > /data/a")
    await ws.shell("ln -s /data/a /data/l")
    link = PathSpec.from_str_path("/data/l")
    items: list[str | PathSpec] = [
        link,
        PathSpec.from_str_path("/data/a"),
        PathSpec.from_str_path("/data/dst")
    ]
    rewritten, moves, early, errors = await prepare_mv(
        ws.namespace, ws.dispatch, items, ("/data/l", "/data/a", "/data/dst"),
        "/")
    assert early is None and errors == []
    assert link not in rewritten
    assert ws.namespace.is_link("/data/dst/l")
    assert not ws.namespace.is_link("/data/l")
    assert moves == [("/data/a", "/data/dst/a", False)]


@pytest.mark.asyncio
async def test_settle_moves_confirms_each_move_by_its_landing():
    # The source cannot confirm a move: a link left below a moved
    # directory synthesizes it back. A landing that appeared is a move
    # that happened; one that was already there waits for exit 0.
    ws = _ws()
    await ws.shell(
        "mkdir -p /data/src /data/new /data/kept; printf k > /data/k")
    await ws.shell("ln -s /data/k /data/src/lk")
    await ws.shell("ln -s /data/k /data/kept/lk")
    await settle_moves(ws.namespace, ws.dispatch, [
        ("/data/src", "/data/new", False),
        ("/data/kept", "/data/gone", False),
        ("/data/kept", "/data/new", True),
    ], 1)
    assert ws.namespace.is_link("/data/new/lk")
    assert not ws.namespace.is_link("/data/src/lk")
    assert ws.namespace.is_link("/data/kept/lk")


@pytest.mark.asyncio
async def test_a_link_below_a_renamed_directory_moves_with_it():
    ws = _ws()
    await ws.shell("mkdir -p /data/d; printf 't\\n' > /data/t")
    await ws.shell("ln -s /data/t /data/d/link")
    assert (await ws.shell("mv /data/d /data/moved")).exit_code == 0
    read = await ws.shell("readlink /data/moved/link")
    assert read.exit_code == 0
    assert read.stdout == b"/data/t\n"
    assert (await ws.shell("cat /data/moved/link")).stdout == b"t\n"
    assert (await ws.shell("readlink /data/d/link")).exit_code != 0


@pytest.mark.asyncio
async def test_ln_refuses_a_slashed_link_name_that_is_not_there():
    # Pinned on coreutils 9.7: symlink(2) and link(2) answer `missing/`
    # with ENOENT and create nothing, the hard-link line naming its
    # source; a directory takes the link inside it as before, and a file
    # behind the slash is still the door's "File exists".
    ws = _ws()
    await ws.shell("printf hi > /data/a.txt; printf y > /data/reg;"
                   " mkdir -p /data/d")
    for line, wording in (
        ("ln -s /data/a.txt /data/missing/",
         "ln: failed to create symbolic link '/data/missing/': "
         "No such file or directory\n"),
        ("ln -sT /data/a.txt /data/missing/",
         "ln: failed to create symbolic link '/data/missing/': "
         "No such file or directory\n"),
        ("ln /data/a.txt /data/missing/",
         "ln: failed to create hard link '/data/missing/' => "
         "'/data/a.txt': No such file or directory\n"),
        ("ln -s /data/a.txt /data/d/missing/",
         "ln: failed to create symbolic link '/data/d/missing/': "
         "No such file or directory\n"),
        ("ln -s /data/a.txt /data/reg/",
         "ln: failed to create symbolic link '/data/reg/': File exists\n"),
    ):
        r = await ws.shell(line)
        assert r.exit_code == 1, line
        assert r.stderr == wording.encode(), line
    assert (await ws.shell("test -e /data/missing")).exit_code == 1
    assert (await ws.shell("test -e /data/d/missing")).exit_code == 1
    assert not ws.namespace.is_link("/data/missing")
    r = await ws.shell("ln -s /data/a.txt /data/d/ && readlink /data/d/a.txt")
    assert r.exit_code == 0
    assert r.stdout == b"/data/a.txt\n"


@pytest.mark.asyncio
async def test_ln_settles_a_slashed_name_before_force_or_backup_touch_it():
    # Pinned on coreutils 9.7: -f and -b lstat the link name first, and
    # `reg/` over a file (or a link to one) is `failed to access 'reg/':
    # Not a directory`, so the file is neither unlinked nor renamed aside.
    ws = _ws()
    await ws.shell("printf hi > /data/a.txt; printf y > /data/reg;"
                   " ln -s /data/reg /data/flink")
    for line in ("ln -sf /data/a.txt /data/reg/",
                 "ln -sb /data/a.txt /data/reg/",
                 "ln -f /data/a.txt /data/reg/",
                 "ln -b /data/a.txt /data/reg/",
                 "ln -sf /data/a.txt /data/flink/"):
        r = await ws.shell(line)
        assert r.exit_code == 1, line
        target = line.split()[-1]
        assert r.stderr == (f"ln: failed to access '{target}': "
                            "Not a directory\n").encode(), line
    assert (await ws.shell("cat /data/reg")).stdout == b"y"
    assert (await ws.shell("test -e /data/reg~")).exit_code == 1
    assert ws.namespace.readlink("/data/flink") == "/data/reg"
    r = await ws.shell("ln -sf /data/a.txt /data/missing/")
    assert r.stderr == (
        b"ln: failed to create symbolic link '/data/missing/': "
        b"No such file or directory\n")
    assert (await ws.shell("test -e /data/missing")).exit_code == 1


@pytest.mark.asyncio
async def test_mv_of_a_link_refuses_a_slashed_destination():
    # Pinned on coreutils 9.7: rename(2) never follows the source, so a
    # link is not a directory whatever it points at; `mv dlnk missing/`
    # refuses at the rename and `mv dlnk reg/` at the destination's stat,
    # and the link stays where it was either way.
    ws = _ws()
    await ws.shell("mkdir -p /data/sd /data/e; printf y > /data/reg;"
                   " ln -s /data/sd /data/dlnk")
    r = await ws.shell("mv /data/dlnk /data/missing/")
    assert r.exit_code == 1
    assert r.stderr == (b"mv: cannot move '/data/dlnk' to '/data/missing/': "
                        b"Not a directory\n")
    r = await ws.shell("mv /data/dlnk /data/reg/")
    assert r.exit_code == 1
    assert r.stderr == b"mv: cannot stat '/data/reg/': Not a directory\n"
    r = await ws.shell("mv /data/dlnk /data/nodir/name/")
    assert r.exit_code == 1
    assert r.stderr == (
        b"mv: cannot move '/data/dlnk' to '/data/nodir/name/': "
        b"No such file or directory\n")
    assert ws.namespace.readlink("/data/dlnk") == "/data/sd"
    assert (await ws.shell("test -e /data/missing")).exit_code == 1
    assert (await ws.shell("cat /data/reg")).stdout == b"y"
    r = await ws.shell("mv /data/dlnk /data/e/ && readlink /data/e/dlnk")
    assert r.exit_code == 0
    assert r.stdout == b"/data/sd\n"


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["missing", "a.txt", "loop"])
async def test_mv_link_into_loop_reports_destination_and_keeps_source(source):
    ws = _ws()
    await ws.shell(
        f"cd /data; echo hello > a.txt; ln -s loop loop; ln -s {source} src")
    result = await ws.shell("cd /data; mv src loop/child")
    assert result.exit_code == 1
    assert result.stderr == (b"mv: cannot stat 'loop/child': "
                             b"Too many levels of symbolic links\n")
    assert ws.namespace.is_link("/data/src")
