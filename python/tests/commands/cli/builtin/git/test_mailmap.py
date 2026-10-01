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

import pytest

from mirage.commands.cli.builtin.git.mailmap import (
    mapped_identity,
    parse_mailmap,
)


@pytest.mark.parametrize(
    "mapping,expected",
    [
        ("Canonical <old@example.com>", "Canonical <old@example.com>"),
        ("<new@example.com> <old@example.com>", "Old <new@example.com>"),
        (
            "Canonical <new@example.com> <old@example.com>",
            "Canonical <new@example.com>",
        ),
        (
            "Canonical <new@example.com> Old <old@example.com>",
            "Canonical <new@example.com>",
        ),
        (
            "Canonical <new@example.com> Someone <old@example.com>",
            "Old <old@example.com>",
        ),
        ("# Canonical <old@example.com>\nbad line", "Old <old@example.com>"),
        ("Canonical <OLD@EXAMPLE.COM>", "Canonical <old@example.com>"),
    ],
)
def test_identity_forms(mapping, expected):
    assert (
        mapped_identity("Old <old@example.com>", parse_mailmap(mapping))
        == expected
    )


def test_specific_identity_wins_over_later_email_mapping():
    mapping = parse_mailmap(
        "Specific <specific@example.com> Old <OLD@example.com>\n"
        "Generic <generic@example.com> <old@example.com>\n"
    )
    assert (
        mapped_identity("Old <old@example.com>", mapping)
        == "Specific <specific@example.com>"
    )
    assert (
        mapped_identity("Another <old@example.com>", mapping)
        == "Generic <generic@example.com>"
    )


def test_a_specific_entry_replaces_the_email_entry_whole():
    mapping = parse_mailmap(
        "Simple <old@example.com>\n<new@example.com> Old <old@example.com>\n"
    )
    assert (
        mapped_identity("Old <old@example.com>", mapping)
        == "Old <new@example.com>"
    )


def test_the_last_specific_entry_for_a_name_wins_whole():
    mapping = parse_mailmap(
        "First <first@example.com> Old <old@example.com>\n"
        "<last@example.com> Old <old@example.com>\n"
    )
    assert (
        mapped_identity("Old <old@example.com>", mapping)
        == "Old <last@example.com>"
    )


def test_later_email_entries_override_only_what_they_spell():
    mapping = parse_mailmap(
        "Name <old@example.com>\n<new@example.com> <old@example.com>\n"
    )
    assert (
        mapped_identity("Old <old@example.com>", mapping)
        == "Name <new@example.com>"
    )


def test_only_a_first_column_hash_is_a_comment():
    mapping = parse_mailmap(" # Hashed <old@example.com>\n")
    assert (
        mapped_identity("Old <old@example.com>", mapping)
        == "# Hashed <old@example.com>"
    )


def test_an_empty_second_email_matches_an_empty_recorded_one():
    mapping = parse_mailmap("Named <named@example.com> Nobody <>\n")
    assert mapped_identity("Nobody <>", mapping) == "Named <named@example.com>"
