from mirage.core.slug_tree.stat import directory_stat
from mirage.core.slug_tree.types import ResolvedDirectory
from mirage.types import FileType


def test_directory_stat_names_the_mount_root_slash():
    root = directory_stat(
        ResolvedDirectory(virtual_key="/knowledge",
                          mount_prefix="/knowledge/"))
    nested = directory_stat(
        ResolvedDirectory(virtual_key="/knowledge/guides",
                          mount_prefix="/knowledge/"))

    assert (root.name, nested.name) == ("/", "guides")
    assert nested.type == FileType.DIRECTORY
    assert nested.extra == {"children_count": 0}
