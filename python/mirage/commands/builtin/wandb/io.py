from mirage.core.wandb.read import read, read_stream
from mirage.core.wandb.readdir import readdir
from mirage.core.wandb.stat import stat
from mirage.vfs.adapter import VFSAdapter
from mirage.vfs.types import NativeReadOps, ReadOps

IO = VFSAdapter(read=ReadOps(readdir=readdir, read_bytes=read, stat=stat),
                native=NativeReadOps(read_stream=read_stream),
                is_mounted=lambda a: True,
                local=False,
                max_du_entries=1000).to_command_io()
