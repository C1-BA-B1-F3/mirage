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

from pydantic import ConfigDict, SecretStr, field_validator

from mirage.secrets.config import AWSAuth
from mirage.utils import key_prefix as kp


class S3Config(AWSAuth):
    model_config = ConfigDict(frozen=True, extra="forbid")

    bucket: str
    endpoint_url: str | None = None
    path_style: bool = False
    timeout: int = 30
    proxy: SecretStr | None = None
    key_prefix: str | None = None
    default_content_type: str | None = None

    @field_validator("key_prefix")
    @classmethod
    def _normalize_key_prefix(cls, v: str | None) -> str | None:
        return kp.normalize(v) or None
