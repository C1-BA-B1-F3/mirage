from mirage.agents import tool_descriptions as shared

NAMES = [
    "EXECUTE_DESCRIPTION",
    "READ_DESCRIPTION",
    "WRITE_DESCRIPTION",
    "EDIT_DESCRIPTION",
    "LS_DESCRIPTION",
    "GREP_DESCRIPTION",
]


def test_every_tool_has_a_description():
    assert sorted(shared.__all__) == sorted(NAMES)
    for name in NAMES:
        assert getattr(shared, name).strip()


def test_edit_description_documents_the_stale_check():
    # The tools refuse an edit to a file that moved since it was read, so
    # the description has to say so or the agent cannot tell that failure
    # from a bad old_string.
    assert "changed since it was last read" in shared.EDIT_DESCRIPTION
    assert "replace_all=true" in shared.EDIT_DESCRIPTION
