import pytest

from mirage.cache.index.config import Evicted
from mirage.cache.index.diff import departed


def _is_folder(kind: str) -> bool:
    return kind == "directory"


@pytest.mark.parametrize("prefix", ["/mount", "/mount/"])
def test_departed_reports_only_topmost_paths(prefix):
    previous = {
        "removed/child": "file",
        "removed": "directory",
        "removed-sibling": "file",
        "kept/deleted": "file",
        "kept": "directory",
        "kept/live": "file",
    }
    assert departed(
        previous.items(), {"kept", "kept/live", "new"}, prefix, _is_folder
    ) == [
        Evicted("/mount/kept/deleted", folder=False),
        Evicted("/mount/removed", folder=True),
        Evicted("/mount/removed-sibling", folder=False),
    ]


@pytest.mark.parametrize("prefix", ["", "/"])
def test_departed_classifies_custom_rows_under_root(prefix):
    previous = {"directory": "directory", "file": "file"}
    assert departed(previous.items(), [], prefix, _is_folder) == [
        Evicted("/directory", folder=True),
        Evicted("/file", folder=False),
    ]


def test_departed_ignores_unchanged_and_new_paths():
    assert (
        departed(
            {"kept": "file"}.items(), ["kept", "new"], "/mount", _is_folder
        )
        == []
    )
    assert departed([], ["new"], "/mount", _is_folder) == []
