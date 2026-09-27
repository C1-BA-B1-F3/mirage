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

from dataclasses import dataclass, field

from mirage.runtime.sandbox.config import SandboxConfig


@dataclass(frozen=True, slots=True, kw_only=True)
class AppleContainerConfig(SandboxConfig):
    """How to reach the user's running containers.

    Args:
        container (str | None): id of the running container a line
            runs in, which is the ``--name`` it was started with (Apple's
            tool keeps no separate name). You start it yourself
            (`container run -d --name my-sandbox ... sleep infinity`);
            live FUSE mounts need `--cap-add SYS_ADMIN` and an image
            with mirage installed. Every container already has
            `/dev/fuse`.
        containers (dict[str, str]): one container per agent, keyed by
            session id: a line from session ``agent_a`` runs in
            ``containers["agent_a"]``, and a session not listed runs in
            ``container``. Separate containers are separate VMs, so the
            agents share no filesystem, processes or view.
    """

    container: str | None = None
    containers: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.container and not self.containers:
            raise ValueError(
                "apple_container config needs container or containers")
