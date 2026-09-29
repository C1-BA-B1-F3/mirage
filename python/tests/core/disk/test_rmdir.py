import pytest

from mirage.accessor.disk import DiskAccessor
from mirage.core.disk.rmdir import rmdir
from mirage.types import PathSpec


# A path under a plain file is ENOTDIR on the real filesystem, and the
# error names the virtual path, never the host one the mount resolves to.
@pytest.mark.asyncio
async def test_rmdir_under_a_plain_file_is_not_a_directory(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    spec = PathSpec(vfs_path="a.txt/x",
                    virtual="/a.txt/x",
                    directory="/a.txt/")
    with pytest.raises(NotADirectoryError) as exc:
        await rmdir(DiskAccessor(tmp_path), spec)
    assert exc.value.filename == "/a.txt/x"
    assert str(tmp_path) not in str(exc.value)
