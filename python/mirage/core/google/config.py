# ========= Copyright 2026 @ Strukto.AI All Rights Reserved. =========
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ========= Copyright 2026 @ Strukto.AI All Rights Reserved. =========

from collections.abc import Callable

from pydantic import BaseModel, ConfigDict, SecretStr, model_validator


class GoogleConfig(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    # Two ways to authenticate, the same two MsGraphConfig offers.
    #
    # A pre-minted token, either a fixed SecretStr or a provider called
    # on every request. The provider is how a caller that already owns
    # the OAuth dance (a service account, a host application's token
    # source) plugs in: it caches and refreshes on its own, so mirage
    # holds no long-lived credential and never contacts the token
    # endpoint. Without it the only way in was `refresh_token`, which a
    # service account cannot produce; a consumer worked around that by
    # monkeypatching `refresh_access_token`.
    access_token: SecretStr | Callable[[], str | SecretStr] | None = None
    # Or the refresh-token grant, where mirage mints and renews the
    # access token itself through TokenManager.
    client_id: str | None = None
    client_secret: SecretStr | None = None
    refresh_token: SecretStr | None = None
    # Single-host override for every Google API (drive/docs/sheets/slides)
    # plus the OAuth token endpoint; used to point backends at a fake server.
    api_base: str | None = None
    # Drive-only: scope the mount to this folder ID instead of the Drive
    # root, the s3 key_prefix analog. Other Google backends ignore it.
    folder_id: str | None = None

    @model_validator(mode="after")
    def _one_credential(self) -> "GoogleConfig":
        """Refuse a config that names neither way to authenticate.

        Both fields became optional so either grant can stand alone, so
        this is what keeps a mount from being built with no credential
        at all and failing on the first read instead.

        Returns:
            GoogleConfig: the validated config.

        Raises:
            ValueError: neither an access_token nor a client_id plus
                refresh_token pair was supplied.
        """
        if self.access_token is not None:
            return self
        if self.client_id is not None and self.refresh_token is not None:
            return self
        raise ValueError(
            "GoogleConfig needs either access_token (a token or a provider "
            "callable) or both client_id and refresh_token")
