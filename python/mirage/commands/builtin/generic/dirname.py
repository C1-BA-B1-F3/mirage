from mirage.commands.spec.usage import missing_operand_error
from mirage.io.types import ByteSource, IOResult
from mirage.utils.path import gnu_dirname


async def dirname(
    *texts: str, zero: bool = False
) -> tuple[ByteSource | None, IOResult]:
    if not texts:
        raise missing_operand_error("dirname", None)
    lines = [gnu_dirname(t) for t in texts]
    separator = "\0" if zero else "\n"
    return (separator.join(lines) + separator).encode(), IOResult()


__all__ = ["dirname"]
