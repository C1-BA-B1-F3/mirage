from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from mirage.core.s3.driver import DRIVER, S3Conn
from mirage.vfs.s3.config import S3Config


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "input,expected",
    [
        ("2026-09-05T10:55:39.000Z", "2026-09-05T10:55:39Z"),
        ("2026-09-05T10:55:39.123Z", "2026-09-05T10:55:39.123000Z"),
    ],
)
async def test_head_and_list_timestamp_format(input, expected):
    modified = datetime.fromisoformat(input)
    client = Mock()
    client.head_object = AsyncMock(
        return_value={"ContentLength": 2, "LastModified": modified}
    )
    pages = MagicMock()
    pages.__aiter__.return_value = [
        {
            "Contents": [
                {"Key": "a.txt", "Size": 2, "LastModified": modified}
            ],
        }
    ]
    client.get_paginator.return_value.paginate.return_value = pages
    conn = S3Conn(client, S3Config(bucket="b"))
    assert (await DRIVER.head(conn, "a.txt")).modified == expected
    children = [child async for child in DRIVER.list_children(conn, "")]
    assert children[0].modified == expected
