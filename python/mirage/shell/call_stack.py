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


@dataclass
class CallFrame:
    positional: list[str] = field(default_factory=list)
    locals: dict[str, str] = field(default_factory=dict)
    function_name: str = ""
    loop_level: int = 0


class CallStack:
    def __init__(self) -> None:
        self._frames: list[CallFrame] = [CallFrame()]

    def fork(self) -> "CallStack":
        child = CallStack()
        child._frames = [
            CallFrame(
                list(frame.positional),
                dict(frame.locals),
                frame.function_name,
                frame.loop_level,
            )
            for frame in self._frames
        ]
        return child

    @property
    def current(self) -> CallFrame:
        return self._frames[-1]

    def push(
        self, positional: list[str] | None = None, function_name: str = ""
    ) -> None:
        self._frames.append(
            CallFrame(
                positional=positional or [],
                function_name=function_name,
            )
        )

    def pop(self) -> CallFrame:
        if len(self._frames) <= 1:
            return self._frames[0]
        return self._frames.pop()

    @property
    def depth(self) -> int:
        return len(self._frames)

    def get_positional(self, index: int) -> str:
        pos = self.current.positional
        if 0 < index <= len(pos):
            return pos[index - 1]
        return ""

    def get_all_positional(self) -> list[str]:
        return self.current.positional

    def get_positional_count(self) -> int:
        return len(self.current.positional)

    def shift(self, n: int = 1) -> None:
        self.current.positional = self.current.positional[n:]

    def set_positional(self, values: list[str]) -> None:
        self.current.positional = values

    def set_local(self, name: str, value: str) -> None:
        self.current.locals[name] = value

    def get_local(self, name: str) -> str | None:
        for frame in reversed(self._frames):
            if name in frame.locals:
                return frame.locals[name]
        return None
