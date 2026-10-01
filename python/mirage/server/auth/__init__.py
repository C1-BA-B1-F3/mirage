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

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mirage.server.auth.config import (AuthConfig, AuthMode, JWTConfig,
                                           resolve_auth_config,
                                           resolve_local_token)
    from mirage.server.auth.middleware import AuthMiddleware
    from mirage.server.auth.storage import (default_token_file,
                                            ensure_token_file, read_token_file)

_EXPORTS: dict[str, tuple[str, ...]] = {
    "mirage.server.auth.config":
    ("AuthConfig", "AuthMode", "JWTConfig", "resolve_auth_config",
     "resolve_local_token"),
    "mirage.server.auth.middleware": ("AuthMiddleware", ),
    "mirage.server.auth.storage":
    ("default_token_file", "ensure_token_file", "read_token_file"),
}
_MODULE_OF = {
    name: module
    for module, names in _EXPORTS.items()
    for name in names
}

__all__ = [
    "AuthConfig",
    "AuthMiddleware",
    "AuthMode",
    "JWTConfig",
    "default_token_file",
    "ensure_token_file",
    "read_token_file",
    "resolve_auth_config",
    "resolve_local_token",
]


def __getattr__(name: str) -> Any:
    module = _MODULE_OF.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(module), name)
    globals()[name] = value
    return value
