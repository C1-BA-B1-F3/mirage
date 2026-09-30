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

from dataclasses import replace

import pytest

from mirage.commands.cli.builtin.git import ref_fields
from mirage.commands.cli.builtin.git.errors import (GitError,
                                                    UnknownDateFormatError,
                                                    UnsupportedFieldError)
from mirage.commands.cli.builtin.git.types import (DateMode, FieldCompare,
                                                   MailmapEntry, RefContext,
                                                   RefItem, RefKind, RefObject,
                                                   RefUpstream)

COMMIT = RefObject(
    oid="c" * 40,
    type="commit",
    raw=(b"tree " + b"t" * 40 + b"\nparent " + b"p" * 40 +
         b"\nauthor A U Thor <author@example.com> 1584244800 +0530\n"
         b"committer C O Mitter <committer@example.com> 1584381600 -0800\n"
         b"\nSubject line\nwraps\n\nBody one.\nBody two.\n"))
TAG = RefObject(
    oid="a" * 40,
    type="tag",
    raw=(b"object " + b"c" * 40 + b"\ntype commit\ntag v1\n"
         b"tagger T Agger <tagger@example.com> 1600000000 +0000\n\n"
         b"Release notes\n\nMore.\n-----BEGIN PGP SIGNATURE-----\nsig\n"
         b"-----END PGP SIGNATURE-----\n"))
BLOB = RefObject(oid="b" * 40, type="blob", raw=b"data\n")
CTX = RefContext(known=frozenset({"refs/heads/main", "refs/tags/main"}),
                 head="refs/heads/main",
                 abbrev=7,
                 date=DateMode(now=1700000000))


def _value(name: str,
           obj: RefObject | None = COMMIT,
           ref: str = "refs/heads/main",
           **kwargs) -> str:
    """One field's text for a ref holding ``obj``.

    Args:
        name (str): the field as typed.
        obj (RefObject | None): the ref's object.
        ref (str): the ref's name.
    """
    item = RefItem(name=ref,
                   oid=obj.oid if obj else "0" * 40,
                   kind=RefKind.BRANCH,
                   obj=obj,
                   **kwargs)
    return ref_fields.field_value(ref_fields.parse_field(name), item, CTX).text


@pytest.mark.parametrize("name,oid", [
    ("objectname", COMMIT.oid),
    ("*objectname", COMMIT.oid),
    ("tree", "t" * 40),
    ("parent", "p" * 40),
])
def test_id_fields_widen_collisions_but_keep_longer_requested_widths(
        name, oid):
    obj = TAG if name.startswith("*") else COMMIT
    item = RefItem(name="refs/tags/v1",
                   oid=obj.oid,
                   kind=RefKind.TAG,
                   obj=obj,
                   peeled=COMMIT)
    ctx = replace(CTX, abbreviations={oid: 8})
    for suffix, width in [("", 40), (":short", 8), (":short=4", 8),
                          (":short=12", 12)]:
        atom = ref_fields.parse_field(name + suffix)
        assert ref_fields.field_value(atom, item, ctx).text == oid[:width]


def test_abbreviation_requests_deduplicate_ids_at_the_smallest_width():
    item = RefItem(name="refs/tags/v1",
                   oid=TAG.oid,
                   kind=RefKind.TAG,
                   obj=TAG,
                   peeled=COMMIT)
    fields = [
        ref_fields.parse_field(name)
        for name in ("refname:short", "objectname", "*objectname:short=12",
                     "*objectname:short", "*objectname:short=4",
                     "*parent:short", "*tree:short=40")
    ]
    assert ref_fields.abbreviation_requests(fields, [item, item], CTX) == {
        COMMIT.oid: 4,
        "p" * 40: 7,
        "t" * 40: 40,
    }


@pytest.mark.parametrize("text,expected", [
    ("2", 2),
    (" +3", 3),
    ("-4", -4),
    ("", None),
    ("2 ", None),
    ("x", None),
    ("99999999999", None),
])
def test_c_int_reads_as_strtol_i(text, expected):
    assert ref_fields.c_int(text) == expected


@pytest.mark.parametrize("text,expected", [("7", 7), ("+7", 7), ("-7", None),
                                           ("0", 0), ("7x", None)])
def test_c_uint_refuses_any_minus(text, expected):
    assert ref_fields.c_uint(text) == expected


@pytest.mark.parametrize("name,message", [
    ("", "malformed field name: "),
    ("*", "malformed field name: *"),
    ("bogus", "unknown field name: bogus"),
    ("refnamex", "unknown field name: refnamex"),
    ("refname:bogus", "unrecognized %(refname) argument: bogus"),
    ("*refname:bogus", "unrecognized %(*refname) argument: bogus"),
    ("refname:lstrip=x", "Integer value expected refname:lstrip=x"),
    ("symref:strip=x", "Integer value expected refname:lstrip=x"),
    ("refname:rstrip=", "Integer value expected refname:rstrip="),
    ("objectname:short=0",
     "positive value expected '0' in %(objectname:short=0)"),
    ("objectname:long", "unrecognized %(objectname) argument: long"),
    ("*objecttype:x", "%(objecttype) does not take arguments"),
    ("contents:lines=-1", "positive value expected contents:lines=-1"),
    ("authoremail:trimfoo", "unrecognized %(authoremail) argument: foo"),
    ("authoremail:trim,", "unrecognized %(authoremail) argument: "),
    ("align", "expected format: %(align:<width>,<position>)"),
    ("align:left", "positive width expected with the %(align) atom"),
    ("align:position=up,5", "unrecognized position:up"),
    ("if:x", "unrecognized %(if) argument: x"),
    ("upstream:short,track", "unrecognized %(upstream) argument: short,track"),
])
def test_a_field_is_refused_in_gits_words(name, message):
    with pytest.raises(GitError) as info:
        ref_fields.parse_field(name)
    assert str(info.value) == message


@pytest.mark.parametrize("name", [
    "describe", "trailers", "contents:trailers", "signature:key", "push",
    "color:red", "objectsize:disk", "ahead-behind:main", "flag"
])
def test_a_field_this_build_lacks_is_unsupported_not_unknown(name):
    with pytest.raises(UnsupportedFieldError) as info:
        ref_fields.parse_field(name)
    assert str(info.value).startswith(f"unsupported field name: {name} ")


def test_a_date_with_a_style_compares_as_text():
    assert ref_fields.parse_field("committerdate").compare is FieldCompare.TIME
    assert ref_fields.parse_field(
        "committerdate:iso").compare is FieldCompare.TEXT
    assert ref_fields.parse_field(
        "contents:size").compare is FieldCompare.NUMBER


@pytest.mark.parametrize("name,expected", [
    ("refs/heads/main", "heads/main"),
    ("refs/tags/main", "tags/main"),
    ("refs/remotes/origin/HEAD", "origin"),
    ("refs/remotes/origin/main", "origin/main"),
    ("refs/notes/commits", "notes/commits"),
    ("refs/heads/HEAD", "heads/HEAD"),
    ("HEAD", "HEAD"),
])
def test_a_ref_shortens_to_what_still_names_it(name, expected):
    known = frozenset({"HEAD", "refs/heads/main", "refs/tags/main"})
    assert ref_fields.shorten_ref(name, known) == expected


def test_a_loose_shortening_ignores_later_rules():
    known = frozenset({"refs/heads/main", "refs/tags/main"})
    assert ref_fields.shorten_ref("refs/tags/main", known,
                                  strict=False) == "main"
    assert ref_fields.shorten_ref("refs/heads/main", known,
                                  strict=False) == "heads/main"


@pytest.mark.parametrize("count,left,right", [
    (0, "refs/heads/feat/x", "refs/heads/feat/x"),
    (1, "heads/feat/x", "refs/heads/feat"),
    (2, "feat/x", "refs/heads"),
    (4, "", ""),
    (-1, "x", "refs"),
    (-3, "heads/feat/x", "refs/heads/feat"),
    (-9, "refs/heads/feat/x", "refs/heads/feat/x"),
])
def test_strip_counts_components_from_either_end(count, left, right):
    assert ref_fields.lstrip_ref("refs/heads/feat/x", count) == left
    assert ref_fields.rstrip_ref("refs/heads/feat/x", count) == right


def test_message_parts_split_subject_body_and_signature():
    message, subject, body, sig = ref_fields.message_parts(TAG.raw.decode())
    assert subject == "Release notes"
    assert message[body:sig] == "More.\n"
    assert message[sig:].startswith("-----BEGIN PGP SIGNATURE-----")


@pytest.mark.parametrize("name,expected", [
    ("subject", "Subject line wraps"),
    ("subject:sanitize", "Subject-line-wraps"),
    ("body", "Body one.\nBody two.\n"),
    ("contents:lines=2", "Subject line\n    wraps"),
    ("contents:size", "40"),
    ("author", "A U Thor <author@example.com> 1584244800 +0530"),
    ("authorname", "A U Thor"),
    ("authoremail", "<author@example.com>"),
    ("authoremail:trim", "author@example.com"),
    ("authoremail:localpart", "author"),
    ("authordate", "Sun Mar 15 09:30:00 2020 +0530"),
    ("authordate:short", "2020-03-15"),
    ("committerdate:unix", "1584381600"),
    ("creator", "C O Mitter <committer@example.com> 1584381600 -0800"),
    ("author:foo", ""),
    ("tree:short", "ttttttt"),
    ("parent:short=4", "pppp"),
    ("numparent", "1"),
    ("tagger", ""),
    ("objectsize", str(len(COMMIT.raw))),
    ("*objectname", ""),
    ("*refname", "refs/heads/main^{}"),
    ("*symref", "^{}"),
    ("HEAD", "*"),
    ("refname:short", "heads/main"),
])
def test_a_commit_field(name, expected):
    assert _value(name) == expected


@pytest.mark.parametrize("name,expected", [
    ("tag", "v1"),
    ("type", "commit"),
    ("object", "c" * 40),
    ("taggername", "T Agger"),
    ("creatordate:iso", "2020-09-13 12:26:40 +0000"),
    ("contents:body", "More.\n"),
    ("contents:signature",
     "-----BEGIN PGP SIGNATURE-----\nsig\n-----END PGP SIGNATURE-----\n"),
    ("authorname", ""),
    ("*objectname", "c" * 40),
    ("*subject", "Subject line wraps"),
    ("*authorname", "A U Thor"),
])
def test_a_tag_field_and_what_it_peels_to(name, expected):
    assert _value(name, TAG, "refs/tags/v1", peeled=COMMIT) == expected


def test_a_bad_date_style_is_refused_only_where_the_date_is():
    assert _value("authordate:bogus", BLOB) == ""
    assert _value("authordate:bogus", TAG, "refs/tags/v1") == ""
    with pytest.raises(UnknownDateFormatError):
        _value("authordate:bogus")


def test_the_mailmap_options_map_the_ident():
    item = RefItem(name="refs/heads/x",
                   oid=COMMIT.oid,
                   kind=RefKind.BRANCH,
                   obj=COMMIT)
    ctx = RefContext(mailmap=(MailmapEntry(email="author@example.com",
                                           name=None,
                                           mapped_name="Alice",
                                           mapped_email=None), ))
    assert ref_fields.field_value(ref_fields.parse_field("authorname:mailmap"),
                                  item, ctx).text == "Alice"
    assert ref_fields.field_value(
        ref_fields.parse_field("authoremail:mailmap,trim"), item,
        ctx).text == "author@example.com"


@pytest.mark.parametrize("name,expected", [
    ("upstream", "refs/remotes/origin/main"),
    ("upstream:short", "origin/main"),
    ("upstream:lstrip=-1", "main"),
    ("upstream:track", "[ahead 1, behind 2]"),
    ("upstream:track,nobracket", "ahead 1, behind 2"),
    ("upstream:trackshort", "<>"),
    ("upstream:remotename", "origin"),
    ("upstream:remoteref", "refs/heads/main"),
])
def test_an_upstream_field(name, expected):
    up = RefUpstream(ref="refs/remotes/origin/main",
                     remote="origin",
                     merge="refs/heads/main",
                     ahead=1,
                     behind=2)
    assert _value(name, upstream=up) == expected
    assert _value(name, ref="refs/tags/main", upstream=up) == ""


def test_a_gone_upstream_tracks_as_gone():
    up = RefUpstream(ref="refs/remotes/origin/x",
                     remote="origin",
                     merge="refs/heads/x",
                     gone=True)
    assert _value("upstream:track", upstream=up) == "[gone]"
    assert _value("upstream:trackshort", upstream=up) == ""
