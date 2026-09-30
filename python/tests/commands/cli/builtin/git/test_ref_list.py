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

from io import BytesIO

import pytest
from dulwich.config import ConfigFile

from mirage.commands.cli.builtin.git import ref_list
from mirage.commands.cli.builtin.git.types import RefKind

SHA = "1" * 40
TABLE = {
    "HEAD": "ref: refs/heads/main",
    "refs/heads/main": SHA,
    "refs/remotes/origin/HEAD": "ref: refs/remotes/origin/main",
    "refs/remotes/origin/main": SHA,
    "refs/remotes/origin/dangling": "ref: refs/remotes/origin/gone",
}


@pytest.mark.parametrize("patterns,expected", [
    ((), True),
    (("refs/heads/feat/git", ), True),
    (("refs/heads", ), True),
    (("refs/heads/", ), True),
    (("refs/hea", ), False),
    (("refs/*", ), False),
    (("refs/*/*", ), False),
    (("refs/*/*/*", ), True),
    (("refs/**", ), True),
    (("**/git", ), True),
    (("refs/heads/feat/g?t", ), True),
    (("refs/tags", "refs/heads/*/git"), True),
])
def test_a_pattern_selects_by_prefix_or_path_glob(patterns, expected):
    assert ref_list.match_as_path("refs/heads/feat/git", patterns) is expected


def test_the_prefix_rule_stays_case_sensitive_under_ignore_case():
    assert ref_list.match_as_path("refs/heads/Main", ("refs/heads/m*", ), True)
    assert not ref_list.match_as_path("refs/heads/Main",
                                      ("refs/HEADS", ), True)


@pytest.mark.parametrize("name,patterns,icase,expected", [
    ("refs/tags/v1.0", ("v1*", ), False, True),
    ("refs/remotes/origin/main", ("origin/*", ), False, True),
    ("refs/heads/feat/x", ("feat*", ), False, True),
    ("refs/heads/Upper", ("u*", ), False, False),
    ("refs/heads/Upper", ("u*", ), True, True),
    ("HEAD", ("ma*", ), False, False),
    ("refs/tags/v1.0", (), False, True),
])
def test_a_short_pattern_matches_past_the_namespace(name, patterns, icase,
                                                    expected):
    assert ref_list.match_short(name, patterns, icase) is expected


def test_a_symbolic_ref_resolves_through_its_target():
    assert ref_list.resolve_ref(
        TABLE, "refs/remotes/origin/HEAD") == (SHA, "refs/remotes/origin/main")
    assert ref_list.resolve_ref(
        TABLE,
        "refs/remotes/origin/dangling") == (None, "refs/remotes/origin/gone")
    assert ref_list.resolve_ref(TABLE, "refs/heads/main") == (SHA, None)
    assert ref_list.head_ref(TABLE) == "refs/heads/main"
    assert ref_list.head_ref({"HEAD": SHA}) == "HEAD"
    assert ref_list.head_ref({"HEAD": "ref: refs/heads/unborn"}) is None


def test_known_names_are_what_resolves_plus_root_refs():
    known = ref_list.known_names(
        TABLE, ["HEAD", "ORIG_HEAD", "config", "packed-refs"])
    assert "refs/remotes/origin/dangling" not in known
    assert {"HEAD", "ORIG_HEAD", "refs/heads/main"} <= known
    assert "config" not in known


@pytest.mark.parametrize("name,expected", [
    ("HEAD", True),
    ("ORIG_HEAD", True),
    ("AUTO_MERGE", True),
    ("FETCH_HEAD", False),
    ("MERGE_HEAD", False),
    ("config", False),
    ("NOT_A_ROOT", False),
])
def test_root_refs_are_gits(name, expected):
    assert ref_list.is_root_ref(name) is expected


@pytest.mark.parametrize("name,kind", [
    ("refs/heads/x", RefKind.BRANCH),
    ("refs/remotes/o/x", RefKind.REMOTE),
    ("refs/tags/x", RefKind.TAG),
    ("HEAD", RefKind.DETACHED),
    ("ORIG_HEAD", RefKind.ROOT),
    ("refs/notes/commits", RefKind.OTHER),
])
def test_a_ref_kind_comes_from_its_name(name, kind):
    assert ref_list.ref_kind(name) is kind


def _config(text: str) -> ConfigFile:
    return ConfigFile.from_file(BytesIO(text.encode()))


def test_an_upstream_maps_through_the_remotes_fetch_refspec():
    cfg = _config("[remote \"origin\"]\n"
                  "\tfetch = +refs/heads/*:refs/remotes/upstream/*\n"
                  "[branch \"main\"]\n\tremote = origin\n"
                  "\tmerge = refs/heads/trunk\n")
    up = ref_list.tracking_ref(cfg, "main", frozenset())
    assert up is not None
    assert (up.ref, up.remote, up.merge) == ("refs/remotes/upstream/trunk",
                                             "origin", "refs/heads/trunk")


def test_no_refspec_means_no_upstream_and_dot_means_local():
    cfg = _config("[branch \"main\"]\n\tremote = origin\n"
                  "\tmerge = refs/heads/main\n"
                  "[branch \"topic\"]\n\tremote = .\n\tmerge = main\n")
    assert ref_list.tracking_ref(cfg, "main", frozenset()) is None
    local = ref_list.tracking_ref(cfg, "topic", frozenset({"refs/heads/main"}))
    assert local is not None and local.ref == "refs/heads/main"
    assert ref_list.tracking_ref(cfg, "other", frozenset()) is None


A1 = "d04348a1" + "0" * 32
A2 = "d04348a2" + "0" * 32
FAR = "d0ffff" + "0" * 34


@pytest.mark.parametrize("oid,width,expected", [
    (A1, 7, 8),
    (A2, 4, 8),
    (FAR, 4, 4),
    ("d04348a3" + "0" * 32, 4, 8),
    (A1, 12, 12),
    (A1, 40, 40),
])
def test_a_width_grows_past_the_neighbours_it_shares(oid, width, expected):
    assert ref_list.unique_width(oid, width, sorted([A1, A2, FAR])) == expected


def test_an_id_alone_in_its_bucket_keeps_its_width():
    assert ref_list.unique_width(A1, 4, []) == 4
