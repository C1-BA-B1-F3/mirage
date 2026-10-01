import pytest

from mirage.core.slug_tree.search import validate_query


def test_validate_query():
    with pytest.raises(ValueError, match="query is required"):
        validate_query("", 10)
    with pytest.raises(ValueError, match="top-k must be positive"):
        validate_query("docs", 0)
