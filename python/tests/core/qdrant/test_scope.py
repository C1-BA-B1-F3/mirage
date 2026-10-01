from mirage.core.hierarchy.scope import INVALID, make_detect_scope
from mirage.core.qdrant.scope import scopes_for
from mirage.core.vector.scope import filters_of
from mirage.types import PathSpec
from mirage.vfs.qdrant.config import QdrantConfig


def _cfg(**kw) -> QdrantConfig:
    base = dict(group_by=["label", "kind"],
                id_field="id",
                text_field="name",
                blob_field="image_bytes",
                blob_ext="png",
                vector_field="vector")
    base.update(kw)
    return QdrantConfig(**base)


def _ps(path: str) -> PathSpec:
    return PathSpec(virtual=path, directory=path, vfs_path=path.strip("/"))


def _detect(config: QdrantConfig):
    return make_detect_scope(scopes_for(config))


def test_row_json():
    config = _cfg()
    match = _detect(config)(_ps("/animals/cat/big/3.json"))
    assert match.kind == "row_json"
    assert match.slots["row_id"] == "3"
    assert filters_of(config.group_by, match) == {
        "label": "cat",
        "kind": "big"
    }


def test_row_text():
    match = _detect(_cfg())(_ps("/animals/cat/big/3.txt"))
    assert match.kind == "row_text"
    assert match.slots["row_id"] == "3"


def test_row_blob():
    match = _detect(_cfg())(_ps("/animals/cat/big/3.png"))
    assert match.kind == "row_blob"
    assert match.slots["row_id"] == "3"


def test_text_needs_text_field():
    match = _detect(_cfg(text_field=None))(_ps("/animals/cat/big/3.txt"))
    assert match.kind == INVALID


def test_blob_needs_blob_field():
    match = _detect(_cfg(blob_field=None))(_ps("/animals/cat/big/3.png"))
    assert match.kind == INVALID
