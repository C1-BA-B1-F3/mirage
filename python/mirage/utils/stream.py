from collections.abc import AsyncIterator


async def _bytes_stream(src: bytes) -> AsyncIterator[bytes]:
    yield src


def ensure_stream(src: bytes | AsyncIterator[bytes]) -> AsyncIterator[bytes]:
    # Preserve the iterator itself so closing the consumer closes its source.
    return _bytes_stream(src) if isinstance(src, bytes) else src
