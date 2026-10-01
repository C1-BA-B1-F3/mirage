from types import SimpleNamespace

import pytest

from mirage.cache.index import RAMIndexCacheStore
from mirage.commands.builtin.dify import COMMANDS
from mirage.commands.builtin.slug_tree.find import _default_name, _expr_texts
from mirage.commands.config import CommandOpts
from mirage.core.dify import tree
from mirage.io.types import IOResult, materialize
from mirage.types import PathSpec
from mirage.utils.key_prefix import mount_key
from tests.commands.builtin.dify.conftest import document

find = next(cmd for cmd in COMMANDS
            if cmd._registered_commands[0].name == "find")


def spec(virtual: str) -> PathSpec:
    return PathSpec.from_str_path(virtual, mount_key(virtual, "/knowledge"))


async def list_documents(config):
    return [
        document("doc-1", "Guide", "guides/quickstart.md"),
        document("doc-2", "Guide 2", "guides/deep/note.md"),
        document("doc-3", "Readme", "README.md"),
    ]


@pytest.fixture(autouse=True)
def documents(monkeypatch):
    monkeypatch.setattr(tree, "list_all_documents", list_documents)


async def run(paths: list[PathSpec], texts: list[str],
              **opts) -> tuple[bytes, IOResult]:
    accessor = SimpleNamespace(config=SimpleNamespace(
        slug_metadata_name="slug"))
    stdout, io = await find(accessor, paths, texts,
                            CommandOpts(index=RAMIndexCacheStore(), **opts))
    return await materialize(stdout), io


@pytest.mark.asyncio
async def test_a_bare_word_is_the_name_filter():
    stdout, io = await run([spec("/knowledge")], ["quick*.md"])

    assert stdout == b"/knowledge/guides/quickstart.md\n"
    assert io.exit_code == 0


@pytest.mark.asyncio
async def test_find_handles_file_missing_and_maxdepth():
    guide = spec("/knowledge/guides/quickstart.md")
    assert (await run([guide], []))[0] == b"/knowledge/guides/quickstart.md\n"
    assert (await run([spec("/knowledge")], [],
                      flags={"maxdepth": "0"}))[0] == b"/knowledge\n"

    stdout, io = await run([spec("/knowledge/missing.md")], [])
    assert stdout == b""
    assert io.stderr is not None
    assert b"/knowledge/missing.md" in io.stderr
    assert io.exit_code == 1


@pytest.mark.asyncio
async def test_find_uses_cwd_when_path_missing():
    guides = PathSpec(vfs_path=mount_key("/knowledge/guides", "/knowledge"),
                      virtual="/knowledge/guides",
                      directory="/knowledge/guides")

    stdout, _ = await run([], ["quick*.md"], cwd=guides)

    assert stdout == b"/knowledge/guides/quickstart.md\n"


@pytest.mark.asyncio
async def test_find_resolves_glob_patterns():
    path = PathSpec(vfs_path=mount_key("/knowledge/guides/*.md", "/knowledge"),
                    virtual="/knowledge/guides/*.md",
                    directory="/knowledge/guides",
                    pattern="*.md",
                    resolved=False)

    assert (await run([path], []))[0] == b"/knowledge/guides/quickstart.md\n"


@pytest.mark.parametrize("texts", [
    ["!", "-name", "x"],
    ["(", "-name", "a", "-o", "-name", "b", ")"],
    ["-name", "x"],
    ["-not", "-name", "x"],
])
def test_expr_texts_preserves_expression(texts):
    assert _expr_texts(texts) == texts


def test_expr_texts_strips_bare_leading_name():
    assert _expr_texts(['foo']) == []
    assert _expr_texts([]) == []


def test_default_name_only_for_bare_word():
    assert _default_name(None, ['foo']) == "foo"
    assert _default_name(None, ['!', '-name', 'x']) is None
    assert _default_name(None, ['(', '-name', 'a']) is None
    assert _default_name('given', ['foo']) == "given"
