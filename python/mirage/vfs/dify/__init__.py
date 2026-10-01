from typing import TYPE_CHECKING

from mirage.vfs.dify.config import DifyConfig

if TYPE_CHECKING:
    from mirage.vfs.dify.dify import DifyVFS

__all__ = ["DifyConfig", "DifyVFS"]


def __getattr__(name: str) -> "type[DifyVFS]":
    if name == "DifyVFS":
        from mirage.vfs.dify.dify import DifyVFS

        return DifyVFS
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
