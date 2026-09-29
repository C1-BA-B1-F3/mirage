from mirage.commands.cli.types import CLIInvocation
from mirage.core.github.config import GhConfig
from mirage.io.types import IOResult
from mirage.version import __version__


async def version(_inv: CLIInvocation[GhConfig]) -> tuple[bytes, IOResult]:
    """Report Mirage's package version instead of an upstream gh build and URL.

    Args:
        _inv (CLIInvocation[GhConfig]): the CLI invocation.
    """
    return f"gh version {__version__} (Mirage)\n".encode(), IOResult()
