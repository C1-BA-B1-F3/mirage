import json

import pytest

from mirage.core.wandb.metadata import run_metadata
from mirage.core.wandb.types import Run, RunVariables

VARIABLES: RunVariables = {
    "entity": "lab",
    "project": "experiments",
    "run": "run-a",
}


def test_unavailable_metadata_is_null_not_invented() -> None:
    result = run_metadata({"name": "run-a"}, VARIABLES)
    assert result["path"] == "lab/experiments/run-a"
    assert result["run"] == "run-a"
    for key in (
        "storage_id",
        "sweep_name",
        "user",
        "created_at",
        "heartbeat_at",
        "system_metrics",
        "tags",
        "history_line_count",
        "file_count",
        "read_only",
    ):
        assert result[key] is None


@pytest.mark.parametrize("encoded", [False, True])
def test_system_metrics_preserve_values_and_structure(encoded: bool) -> None:
    metrics = {
        "cpu": 0,
        "memory": 1.5,
        "nested": {"missing": None},
        "label": "café",
    }
    run: Run = {
        "name": "run-a",
        "systemMetrics": json.dumps(metrics) if encoded else metrics,
    }
    assert run_metadata(run, VARIABLES)["system_metrics"] == metrics


def test_empty_values_and_run_identity_are_preserved() -> None:
    result = run_metadata(
        {
            "name": "run-a",
            "id": "opaque-storage-id",
            "displayName": "duplicate",
            "tags": [],
            "notes": "",
            "group": "",
            "readOnly": False,
            "fileCount": 0,
            "historyLineCount": 0,
            "createdAt": "2026-01-01T08:00:00+08:00",
            "user": {
                "id": "opaque-user-id",
                "name": "",
                "username": "bob",
                "email": None,
            },
            "historyKeys": {"lastStep": -1, "keys": {}},
            "config": {"lr": {"value": 0.01}},
            "summaryMetrics": {"score": 0.9},
        },
        VARIABLES,
    )
    assert result["run"] == "run-a"
    assert result["storage_id"] == "opaque-storage-id"
    assert result["display_name"] == "duplicate"
    assert result["tags"] == []
    assert result["notes"] == result["group"] == ""
    assert result["read_only"] is False
    assert result["file_count"] == result["history_line_count"] == 0
    assert result["user"] == {
        "id": "opaque-user-id",
        "name": "",
        "username": "bob",
        "email": None,
    }
    assert result["created_at"] == "2026-01-01T08:00:00+08:00"
    assert result["history_keys"] == {"lastStep": -1, "keys": {}}
    assert "config" not in result and "summaryMetrics" not in result


@pytest.mark.parametrize("raw", ["", "malformed"])
def test_malformed_system_metrics_fail(raw: str) -> None:
    with pytest.raises(json.JSONDecodeError):
        run_metadata({"name": "run-a", "systemMetrics": raw}, VARIABLES)
