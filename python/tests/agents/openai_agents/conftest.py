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

import json
from typing import Any

import pytest
from agents.items import ModelResponse, TResponseInputItem
from agents.models.interface import Model
from agents.usage import Usage
from openai.types.responses import (
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
)


class ScriptedModel(Model):
    """A model that calls the scripted tools in order, then answers.

    The answer is the last tool output it saw, so a test reads what the
    sandbox returned from ``result.final_output``.

    Args:
        calls (list[tuple[str, dict[str, Any]]]): Tool name and
            arguments per turn.
    """

    def __init__(self, calls: list[tuple[str, dict[str, Any]]]) -> None:
        self.calls = list(calls)
        self.instructions: list[str | None] = []

    async def get_response(
        self,
        system_instructions: str | None,
        input: str | list[TResponseInputItem],
        *args: Any,
        **kwargs: Any,
    ) -> ModelResponse:
        self.instructions.append(system_instructions)
        turn = len(self.instructions)
        if self.calls:
            name, arguments = self.calls.pop(0)
            item: Any = ResponseFunctionToolCall(
                type="function_call",
                call_id=f"call-{turn}",
                id=f"fc-{turn}",
                name=name,
                arguments=json.dumps(arguments),
                status="completed",
            )
        else:
            item = ResponseOutputMessage(
                id=f"msg-{turn}",
                type="message",
                role="assistant",
                status="completed",
                content=[
                    ResponseOutputText(
                        type="output_text",
                        text=last_output(input),
                        annotations=[],
                    )
                ],
            )
        return ModelResponse(output=[item], usage=Usage(), response_id=None)

    def stream_response(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError


def last_output(items: str | list[TResponseInputItem]) -> str:
    if isinstance(items, str):
        return ""
    for item in reversed(items):
        if (
            isinstance(item, dict)
            and item.get("type") == "function_call_output"
        ):
            return str(item.get("output"))
    return ""


@pytest.fixture
def scripted_model() -> type[ScriptedModel]:
    return ScriptedModel
