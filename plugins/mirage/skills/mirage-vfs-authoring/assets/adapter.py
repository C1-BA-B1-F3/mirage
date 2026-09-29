import asyncio

from mirage import (Accessor, BaseVFS, FileStat, FileType, PathSpec,
                    ReadFixture, ReadOps, VFSAdapter, Workspace,
                    check_read_contract)


class ResourceClient(Accessor):

    def __init__(self) -> None:
        self.files = {"hello.txt": b"Hello from my resource!\n"}


async def read_bytes(client: ResourceClient,
                     path: PathSpec,
                     index=None) -> bytes:
    key = path.vfs_path.strip("/")
    if not key:
        raise IsADirectoryError(path.virtual)
    if key not in client.files:
        raise FileNotFoundError(path.virtual)
    return client.files[key]


async def readdir(client: ResourceClient,
                  path: PathSpec,
                  index=None) -> list[str]:
    if path.vfs_path.strip("/"):
        await read_bytes(client, path, index)
        raise NotADirectoryError(path.virtual)
    return [
        f"{path.virtual.rstrip('/')}/{name}" for name in sorted(client.files)
    ]


async def stat(client: ResourceClient, path: PathSpec, index=None) -> FileStat:
    name = path.virtual.rstrip("/").rsplit("/", 1)[-1] or "/"
    if not path.vfs_path.strip("/"):
        return FileStat(name=name, type=FileType.DIRECTORY)
    data = await read_bytes(client, path, index)
    return FileStat(name=name, type=FileType.FILE, size=len(data))


ADAPTER = VFSAdapter(
    read=ReadOps(readdir=readdir, read_bytes=read_bytes, stat=stat))


async def main() -> None:
    client = ResourceClient()
    fixture = ReadFixture(
        file=PathSpec(virtual="/resource/hello.txt",
                      directory="/resource",
                      vfs_path="hello.txt"),
        directory=PathSpec(virtual="/resource", directory="/", vfs_path=""),
        missing=PathSpec(virtual="/resource/missing",
                         directory="/resource",
                         vfs_path="missing"),
        content=client.files["hello.txt"],
    )
    await check_read_contract(ADAPTER, client, fixture)
    ws = Workspace(
        {"/resource": BaseVFS(name="resource", accessor=client, io=ADAPTER)})
    try:
        result = await ws.shell("cat /resource/hello.txt")
        assert result.exit_code == 0
        assert await result.stdout_str() == fixture.content.decode()
    finally:
        await ws.close()


if __name__ == "__main__":
    asyncio.run(main())
