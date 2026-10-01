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

from pydantic import BaseModel, ConfigDict, SecretStr


class SSHConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    host: str
    hostname: str | None = None
    port: int | None = None
    username: str | None = None
    identity_file: str | None = None
    # Password authentication, and the passphrase of an encrypted
    # identity_file. Both are credentials, so both are SecretStr and both
    # redact out of snapshot state; without them a password-only host and
    # an encrypted key were unreachable, and a config naming either had the
    # key dropped by pydantic's extra="ignore" without a word.
    password: SecretStr | None = None
    passphrase: SecretStr | None = None
    root: str = "/"
    timeout: int = 30
    known_hosts: str | None = None
