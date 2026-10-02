from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, SecretStr


def entity_name(value: str) -> str:
    if value in (".", ".."):
        raise ValueError("entity must be a filesystem name")
    return value


Name = Annotated[
    str,
    Field(pattern=r"^[^/\\\x00]+$", min_length=1),
    AfterValidator(entity_name),
]


class WandbConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    entities: list[Name] = Field(min_length=1)
    api_key: SecretStr = SecretStr("")
    base_url: str = "https://api.wandb.ai"
    page_size: int = Field(default=100, ge=1, le=1000)
    max_pages: int = Field(default=10000, ge=1)
