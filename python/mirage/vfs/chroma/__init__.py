from typing import TYPE_CHECKING

from mirage.vfs.chroma.config import ChromaConfig

if TYPE_CHECKING:
    from mirage.vfs.chroma.chroma import ChromaVFS

__all__ = ["ChromaConfig", "ChromaVFS"]


def __getattr__(name: str) -> "type[ChromaVFS]":
    if name == "ChromaVFS":
        from mirage.vfs.chroma.chroma import ChromaVFS
        return ChromaVFS
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
