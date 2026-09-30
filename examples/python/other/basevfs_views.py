import asyncio

from mirage import (NULL_INDEX, Accessor, BaseVFS, CLIInvocation, CLISpec,
                    ContentType, FileStat, FileType, IndexCacheStore, IOResult,
                    MountMode, Operand, PathSpec, ReadOps, VFSAdapter,
                    Workspace)
from mirage.runtime.vfs import RuntimeVFS


class NotesAccessor(Accessor):

    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = dict(pages)


def page_bytes(accessor: NotesAccessor, path: PathSpec) -> bytes:
    key = path.vfs_path.strip("/")
    if not key:
        raise IsADirectoryError(path.virtual)
    if "/" in key and key.split("/", 1)[0] in accessor.pages:
        raise NotADirectoryError(path.virtual)
    page = accessor.pages.get(key)
    if page is None:
        raise FileNotFoundError(path.virtual)
    return page.encode("utf-8")


async def readdir(accessor: NotesAccessor,
                  path: PathSpec,
                  index: IndexCacheStore = NULL_INDEX) -> list[str]:
    if path.vfs_path.strip("/"):
        page_bytes(accessor, path)
        raise NotADirectoryError(path.virtual)
    parent = path.virtual.rstrip("/")
    return [f"{parent}/{name}" for name in sorted(accessor.pages)]


async def read_bytes(accessor: NotesAccessor,
                     path: PathSpec,
                     index: IndexCacheStore = NULL_INDEX) -> bytes:
    return page_bytes(accessor, path)


async def stat(accessor: NotesAccessor,
               path: PathSpec,
               index: IndexCacheStore = NULL_INDEX) -> FileStat:
    name = path.virtual.rstrip("/").rsplit("/", 1)[-1] or "/"
    if not path.vfs_path.strip("/"):
        return FileStat(name=name, type=FileType.DIRECTORY, size=None)
    return FileStat(name=name,
                    type=FileType.FILE,
                    content=ContentType.TEXT,
                    size=len(page_bytes(accessor, path)))


class NotesVFS(BaseVFS):
    """A flat, read-only collection of UTF-8 pages."""

    def __init__(self, pages: dict[str, str]) -> None:
        super().__init__(
            name="notes",
            accessor=NotesAccessor(pages),
            io=VFSAdapter(read=ReadOps(
                readdir=readdir, read_bytes=read_bytes, stat=stat)),
            prompt="Read-only notes rendered as UTF-8 text files.",
            sizes_always_known=True,
        )


async def note_info(inv: CLIInvocation[None]) -> tuple[bytes, IOResult]:
    doors = inv.doors
    if (doors is None or doors.dispatch is None or doors.ns is None
            or doors.ns.mounts is None or doors.session_view is None):
        raise RuntimeError("note-info needs workspace doors")
    path = inv.paths[0]
    target = (doors.ns.links.resolve(path.virtual)
              if doors.ns.links is not None else path.virtual)
    data, result = await doors.dispatch("read", path)
    if result.exit_code != 0:
        return b"", result
    if not isinstance(data, bytes):
        raise TypeError("expected file bytes")
    mount = doors.ns.mounts.root_of(target)
    reader = doors.session_view.get("READER") or "anonymous"
    header = f"mount={mount} reader={reader} bytes={len(data)}\n"
    return header.encode() + data, result


async def show(ws: Workspace, line: str) -> None:
    result = await ws.shell(line)
    if result.exit_code != 0:
        raise RuntimeError(f"{line}: {await result.stderr_str()}")
    print(f"$ {line}\n{await result.stdout_str()}", end="")


async def main() -> None:
    ws = Workspace(
        {
            "/notes":
            NotesVFS({
                "welcome.txt": "Hello, café.\n",
                "todo.txt": "Review the BaseVFS adapter.\n",
            }),
            "/notes/status":
            NotesVFS({"health.txt": "ok\n"}),
        },
        mode=MountMode.WRITE,
    )
    try:
        ws.register_cli(
            "note-info",
            CLISpec(name="note-info",
                    positional=(Operand(name="path",
                                        type="path",
                                        required=True), ),
                    fn=note_info),
        )
        for line in (
                "ln -s /notes/welcome.txt /latest",
                "ls -1 /notes",
                "cat /latest",
                "grep BaseVFS /notes/todo.txt",
                "export READER=demo; note-info /latest",
                "note-info /notes/status/health.txt",
        ):
            await show(ws, line)

        expected = "Hello, café.\n".encode()
        assert await ws.vfs.read("/latest") == expected
        assert (await ws.vfs.stat("/latest")).size == len(expected)
        reader = await ws.session("reader", {"/notes": MountMode.READ})
        assert await reader.vfs.read("/latest") == expected

        runtime = RuntimeVFS(ws.dispatch, asyncio.get_running_loop())
        assert await asyncio.to_thread(runtime.read, "/latest") == expected
        assert not (await asyncio.to_thread(runtime.stat, "/latest")).is_dir
        refused = await ws.shell("echo changed > /notes/welcome.txt")
        assert refused.exit_code != 0
        assert await ws.vfs.read("/latest") == expected
        print(
            "Filesystem, session and runtime views agree; writes are refused.")
    finally:
        await ws.close()


if __name__ == "__main__":
    asyncio.run(main())
