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

PROMPT = """\
{prefix}
  <guild-name>__<guild-id>/
    channels/
      <channel-name>__<channel-id>/
        <yyyy-mm-dd>/
          chat.jsonl              # messages for that date
          files/                  # attachments shared that day (may be empty)
            <name>__<att-id>.<ext>  # cat to download bytes from Discord CDN
    members/
      <username>__<user-id>.json  # member profile
  Naming: guild, channel, member, attachment names are `<display-name>__<id>`.
  The display name keeps the original spelling from Discord (spaces,
  apostrophes, emoji); only `/` is replaced with `∕` (U+2215) so paths
  don't break. Quote names containing spaces in shell commands. Always
  ls the parent dir first to discover exact entry names (they include
  IDs).
  Without time bounds, bare channel listings show the latest 30 days
  ending at the newest message. Date globs can discover earlier days.
  With start_time/end_time, listings cover that scope; messages and their
  attachments outside it are absent, including through direct paths.
  Users and channel metadata remain available as context.
  A time-scoped mount does not search through Discord: grep and rg read
  the in-scope files, so grep needs -r to search a directory.
  Messages are JSONL; use jq to extract fields like .content, .author.username,
  .attachments.
  grep / rg at channel or guild scope uses Discord's `/messages/search` API
  and ONLY searches message text. It does NOT index attachment content
  (unlike Slack's `search.files`). To search inside text attachments
  (.txt, .md, .log), target the date dir, files/ dir, or specific blob path
  so grep falls back to per-file scan via CDN download. Binary attachments
  (JPG, PDF) will produce noise."""

WRITE_PROMPT = """\
  Writes go through the discord CLI if installed:
    discord send --channel <channel-id> --text "message"
    discord react --channel <channel-id> --message <id> --emoji "✅"
  See discord --help for every verb (edit, delete, threads, polls)."""
