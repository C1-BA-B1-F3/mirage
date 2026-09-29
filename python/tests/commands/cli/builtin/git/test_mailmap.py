import pytest

from mirage.commands.cli.builtin.git.mailmap import (mapped_identity,
                                                     parse_mailmap)


@pytest.mark.parametrize('mapping,expected', [
    ('Canonical <old@example.com>', 'Canonical <old@example.com>'),
    ('<new@example.com> <old@example.com>', 'Old <new@example.com>'),
    ('Canonical <new@example.com> <old@example.com>',
     'Canonical <new@example.com>'),
    ('Canonical <new@example.com> Old <old@example.com>',
     'Canonical <new@example.com>'),
    ('Canonical <new@example.com> Someone <old@example.com>',
     'Old <old@example.com>'),
    ('# Canonical <old@example.com>\nbad line', 'Old <old@example.com>'),
])
def test_identity_forms(mapping, expected):
    assert mapped_identity('Old <old@example.com>',
                           parse_mailmap(mapping)) == expected


def test_specific_identity_wins_over_later_email_mapping():
    mapping = parse_mailmap(
        'Specific <specific@example.com> Old <OLD@example.com>\n'
        'Generic <generic@example.com> <old@example.com>\n')
    assert mapped_identity('Old <old@example.com>',
                           mapping) == 'Specific <specific@example.com>'
    assert mapped_identity('Another <old@example.com>',
                           mapping) == 'Generic <generic@example.com>'
