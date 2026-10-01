import json
from typing import Any

from mirage.core.wandb.types import Run, RunVariables


def run_metadata(run: Run, variables: RunVariables) -> dict[str, Any]:
    system_metrics = run.get("systemMetrics")
    if isinstance(system_metrics, str):
        system_metrics = json.loads(system_metrics)
    run_path = "/".join(
        (variables["entity"], variables["project"], variables["run"])
    )
    return {
        **variables,
        "path": run_path,
        "storage_id": run.get("id"),
        "display_name": run.get("displayName"),
        "state": run.get("state"),
        "tags": run.get("tags"),
        "sweep_name": run.get("sweepName"),
        "group": run.get("group"),
        "job_type": run.get("jobType"),
        "commit": run.get("commit"),
        "read_only": run.get("readOnly"),
        "created_at": run.get("createdAt"),
        "heartbeat_at": run.get("heartbeatAt"),
        "description": run.get("description"),
        "notes": run.get("notes"),
        "user": run.get("user"),
        "system_metrics": system_metrics,
        "history_line_count": run.get("historyLineCount"),
        "history_keys": run.get("historyKeys"),
        "file_count": run.get("fileCount"),
    }
