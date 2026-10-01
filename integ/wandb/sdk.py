import base64
import hashlib
import json
import os
import tempfile
from pathlib import Path

import requests
import wandb


def main() -> None:
    version = os.environ["MIRAGE_WANDB_SDK_VERSION"]
    assert wandb.__version__ == version
    api = wandb.Api(
        overrides={"base_url": os.environ["WANDB_BASE_URL"], "entity": "lab"},
        api_key=os.environ["WANDB_API_KEY"],
        timeout=5,
    )
    assert api.viewer.username == "alice"
    assert api.viewer.entity == "lab"
    assert api.viewer.teams == ["lab", "other"]
    assert [p.name for p in api.projects("lab", per_page=1)] == [
        "empty",
        "experiments",
    ]
    assert api.project("experiments", "lab").name == "experiments"
    assert list(api.runs("lab/empty")) == []
    filters = {"name": {"$ne": "run-b"}}
    assert [
        r.id for r in api.runs("lab/experiments", filters=filters, per_page=1)
    ] == ["run-a", "run-long"]
    assert [
        r.id
        for r in api.runs(
            "lab/experiments", filters=filters, order="-created_at", per_page=1
        )
    ] == ["run-long", "run-a"]
    assert [
        r.id
        for r in api.runs(
            "lab/experiments", filters={"summary_metrics.score": {"$gt": 0.3}}
        )
    ] == ["run-a"]
    run = api.run("lab/experiments/run-a")
    assert run.id == "run-a" and run.name == "duplicate"
    assert run.storage_id == "synthetic-storage-id-a"
    assert run.group == "ablation" and run.job_type == "train"
    assert run.sweep.id == "sweep-01" and run.sweep.name == "Synthetic sweep"
    assert run.user.username == "bob"
    assert run.config == {"lr": 0.01, "label": "café"}
    assert run.summary["score"] == 0.4
    rows = [
        {"_step": 0, "train_step": 0, "score": 0.1},
        {"_step": 1, "train_step": 100, "score": 0.9},
        {"_step": 4, "train_step": 400, "loss": None},
        {"_step": 5, "train_step": 500, "score": 0.4},
    ]
    assert list(run.scan_history(page_size=2)) == rows
    assert (
        list(run.scan_history(page_size=2, min_step=1, max_step=5))
        == rows[1:3]
    )
    assert list(run.scan_history(keys=["_step", "score"], page_size=2)) == [
        {"_step": r["_step"], "score": r["score"]}
        for r in rows
        if "score" in r
    ]
    assert run.history(samples=10, pandas=False) == rows
    assert run.history(samples=10, keys=["score"], pandas=False) == [
        {"score": r["score"], "_step": r["_step"]}
        for r in rows
        if "score" in r
    ]
    assert (
        len(
            list(
                api.run("lab/experiments/run-long").scan_history(
                    page_size=2000
                )
            )
        )
        == 2048
    )
    files = list(run.files(per_page=1))
    assert [f.name for f in files] == [
        "notes.txt",
        "nested/log.txt",
        "nested/model.bin",
        "large.txt",
    ]
    file = run.file("nested/model.bin")
    expected = bytes([0, 1, 2, 255])
    assert file.size == len(expected)
    assert (
        file.md5 == base64.b64encode(hashlib.md5(expected).digest()).decode()
    )
    with tempfile.TemporaryDirectory() as directory:
        with file.download(root=directory, api=api) as downloaded:
            assert Path(downloaded.name).read_bytes() == expected
    response = requests.get(file._attrs["directUrl"], timeout=5)
    response.raise_for_status()
    assert response.content == expected
    try:
        api.run("lab/experiments/missing-run")
    except (ValueError, wandb.errors.CommError):
        pass
    else:
        raise AssertionError("Missing run must fail")
    if version == "0.29.0":
        try:
            api.run("lab/experiments/run-b")
        except wandb.errors.CommError as error:
            assert "'NoneType' object is not iterable" in str(error)
        else:
            raise AssertionError(
                "Recheck null-creator handling; SDK 0.29.0 behavior changed"
            )
        print(
            "Known upstream SDK 0.29.0 limitation reproduced: "
            "null run creator raises CommError"
        )
    else:
        assert (
            list(api.run("lab/experiments/run-b").scan_history(page_size=2))
            == []
        )
    print(json.dumps({"sdk": version, "status": "passed"}))


if __name__ == "__main__":
    main()
