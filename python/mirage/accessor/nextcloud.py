from typing import TYPE_CHECKING

import opendal

from mirage.accessor.base import Accessor
from mirage.vfs.secrets import reveal_secret

if TYPE_CHECKING:
    from mirage.vfs.nextcloud.nextcloud import NextcloudConfig


class NextcloudAccessor(Accessor):

    def __init__(self, config: "NextcloudConfig") -> None:
        self.config = config

    def operator(self):
        config = self.config
        kwargs = {"endpoint": config.url}
        username = reveal_secret(config.username)
        if username:
            kwargs["username"] = username
        password = reveal_secret(config.password)
        if password:
            kwargs["password"] = password
        return opendal.AsyncOperator("webdav", **kwargs)
