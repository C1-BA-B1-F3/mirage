from unittest.mock import AsyncMock

import pytest

from mirage.core.api.client import SessionPool
from mirage.core.wandb.client import WandbClient
from mirage.core.wandb.config import WandbConfig
from mirage.core.wandb.queries import RUN_CONFIG, RUN_EXISTS, RUN_SUMMARY


@pytest.mark.asyncio
@pytest.mark.parametrize("query", [RUN_EXISTS, RUN_CONFIG, RUN_SUMMARY])
async def test_run_identifiers_are_bound_as_variables(
    query: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    identifier = 'run") { user { email } } #'
    request = AsyncMock(
        return_value={"data": {"project": {"run": {"name": identifier}}}}
    )
    monkeypatch.setattr("mirage.core.wandb.client.api_request", request)
    client = WandbClient(WandbConfig(entities=["lab"]), SessionPool())
    variables = {"entity": "lab", "project": "project", "run": identifier}
    result = await client.run(variables, query)
    assert result["name"] == identifier
    body = request.call_args.kwargs["json_body"]
    assert body["variables"] == variables
    assert body["query"] == query
    assert identifier not in body["query"]
