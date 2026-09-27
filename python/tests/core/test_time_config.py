import pytest
from pydantic import ValidationError

from mirage.core.discord.config import DiscordConfig
from mirage.core.slack.config import SlackConfig
from mirage.vfs.gcal.config import GCalConfig


@pytest.mark.parametrize("model,credentials", [
    (SlackConfig, {
        "token": "test"
    }),
    (DiscordConfig, {
        "token": "test"
    }),
    (GCalConfig, {
        "access_token": "test"
    }),
])
def test_time_bounds_validate_and_serialize(model, credentials):
    config = model(**credentials,
                   start_time="2026-06-01T10:00:00+08:00",
                   end_time="2026-06-01T03:00:00Z")
    assert config.model_dump()["start_time"] == "2026-06-01T10:00:00+08:00"
    assert model(**credentials, start_time=None,
                 end_time=None).end_time is None
    for start, end in [
        ("2026-06-01", None),
        ("2026-06-01T10:00:00", None),
        ("2026-02-30T10:00:00Z", None),
        ("2026-06-01T24:00:00Z", None),
        ("2026-06-01T10:00:00+01:60", None),
        ("0000-06-01T10:00:00Z", None),
        ("2026-06-01T10:00:00.000001Z", None),
        ("2026-06-01T10:00:00Z", "2026-06-01T10:00:00Z"),
        ("2026-06-01T10:00:00Z", "2026-06-01T10:00:00+08:00"),
    ]:
        with pytest.raises(ValidationError):
            model(**credentials, start_time=start, end_time=end)
