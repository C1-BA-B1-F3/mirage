import pytest

from mirage.core.nextcloud.util import nextcloud_key, raw_path_of
from mirage.types import PathSpec


def _mounted(virtual: str, vfs_path: str) -> PathSpec:
    return PathSpec(virtual=virtual, directory=virtual, vfs_path=vfs_path)


@pytest.mark.parametrize(
    ("virtual", "vfs_path", "raw", "key"),
    [
        ("/nc/docs/a.txt", "docs/a.txt", "/docs/a.txt", "docs/a.txt"),
        ("/nc", "", "/", ""),
        ("/nc/", "", "/", ""),
        ("/nc/docs/", "docs", "/docs/", "docs/"),
        ("/a.txt", "a.txt", "/a.txt", "a.txt"),
    ],
)
def test_raw_path_and_key_drop_the_mount_prefix(virtual, vfs_path, raw, key):
    path = _mounted(virtual, vfs_path)
    assert raw_path_of(path) == raw
    assert nextcloud_key(path) == key
