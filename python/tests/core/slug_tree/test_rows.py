import pytest

from mirage.core.slug_tree.rows import normalize_slug, virtual_path


def test_normalize_slug_folds_slashes_and_names_the_backend():
    assert normalize_slug("/a//b/", "Chroma path") == "/a/b"
    with pytest.raises(ValueError, match="Invalid empty Chroma path"):
        normalize_slug("//", "Chroma path")
    with pytest.raises(
        ValueError, match="Invalid Dify document slug segment: '..'"
    ):
        normalize_slug("a/../b", "Dify document slug")


def test_virtual_path_maps_tree_paths_under_the_mount_root():
    assert virtual_path("/", "/knowledge/") == "/knowledge"
    assert virtual_path("/guides", "/knowledge/") == "/knowledge/guides"
    assert virtual_path("/guides", "") == "/guides"
