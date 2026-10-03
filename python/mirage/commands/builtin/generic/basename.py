from mirage.commands.spec.usage import (
    extra_operand_error,
    missing_operand_error,
)
from mirage.io.types import ByteSource, IOResult
from mirage.utils.path import gnu_basename


async def basename(
    *texts: str,
    multiple: bool = False,
    suffix: str | None = None,
    zero: bool = False,
) -> tuple[ByteSource | None, IOResult]:
    if not texts:
        raise missing_operand_error("basename", None)
    if suffix is None and not multiple and len(texts) > 2:
        raise extra_operand_error("basename", texts[2])
    if suffix is not None:
        lines = [gnu_basename(text, suffix) for text in texts]
    elif len(texts) == 2 and not multiple:
        lines = [gnu_basename(texts[0], texts[1])]
    else:
        lines = [gnu_basename(t) for t in texts]
    separator = "\0" if zero else "\n"
    return (separator.join(lines) + separator).encode(), IOResult()


__all__ = ["basename"]
