from collections.abc import Callable, Iterable
from operator import itemgetter
from typing import TypeVar

from mirage.cache.index.config import Evicted

T = TypeVar("T")


def departed(
    previous: Iterable[tuple[str, T]],
    current: Iterable[str],
    prefix: str,
    is_folder: Callable[[T], bool],
) -> list[Evicted]:
    """Return topmost paths absent from a replacement tree.

    Args:
        previous (Iterable[tuple[str, T]]): previous relative paths and rows.
        current (Iterable[str]): replacement relative paths.
        prefix (str): mount prefix for the returned paths.
        is_folder (Callable[[T], bool]): classify a previous row.
    """
    present = set(current)
    gone = sorted(
        ((path, entry) for path, entry in previous if path not in present),
        key=itemgetter(0),
    )
    top: list[str] = []
    result: list[Evicted] = []
    stem = prefix.rstrip("/")
    for path, entry in gone:
        if not any(path.startswith(kept + "/") for kept in top):
            top.append(path)
            result.append(Evicted(f"{stem}/{path}", folder=is_folder(entry)))
    return result
