import pytest

from mirage.commands.cli.builtin.gh import GH
from mirage.io.types import materialize
from mirage.version import __version__
from mirage.workspace import Workspace


@pytest.mark.asyncio
@pytest.mark.parametrize("form", ["version", "--version"])
async def test_reports_version_without_a_mount_or_api(form):
    with Workspace({}) as ws:
        ws.register_cli(
            "gh", GH, {"token": "unused", "base_url": "http://127.0.0.1:1"}
        )
        result = await ws.shell(f"gh {form}")
        assert result.exit_code == 0
        assert (
            await materialize(result.stdout)
            == f"gh version {__version__} (Mirage)\n".encode()
        )
        assert not result.stderr
