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


class AwkSyntaxError(Exception):
    pass


class AwkRuntimeError(Exception):
    pass


class AwkIOError(Exception):
    """An input or output stream awk could not open, read or write.

    The host raises it with the system's reason; the interpreter decides
    whether the failure is fatal (a main input, an output file) or a
    getline result of -1.

    Args:
        detail (str): the strerror text, such as ``No such file or
            directory``.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


__all__ = ["AwkIOError", "AwkRuntimeError", "AwkSyntaxError"]
