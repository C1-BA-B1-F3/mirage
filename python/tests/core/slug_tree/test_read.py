import pytest

from mirage.core.slug_tree.read import file_entry

from .conftest import spec


@pytest.mark.asyncio
async def test_file_entry_refuses_a_folder(tree, index):
    entry = await file_entry(
        tree, None, spec("/knowledge/guides/quickstart"), index
    )

    assert entry.id == "guides/quickstart"
    with pytest.raises(IsADirectoryError):
        await file_entry(tree, None, spec("/knowledge/guides"), index)
