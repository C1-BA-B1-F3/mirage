import pytest

from mirage.commands.builtin.generic.basename import basename
from mirage.commands.errors import UsageError


@pytest.mark.asyncio
async def test_basename_without_an_operand_is_a_usage_error():
    with pytest.raises(UsageError, match="basename: missing operand"):
        await basename()
