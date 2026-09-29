// ========= Copyright 2026 @ Strukto.AI All Rights Reserved. =========
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.
// ========= Copyright 2026 @ Strukto.AI All Rights Reserved. =========

export const TRELLO_PROMPT = `{prefix}
  workspaces/
    <workspace-name>__<workspace-id>/
      workspace.json
      boards/
        <board-name>__<board-id>/
          board.json
          members/
            <full-name>__<member-id>.json
          labels/
            <label-name>__<label-id>.json
          lists/
            <list-name>__<list-id>/
              list.json
              cards/
                <card-name>__<card-id>/
                  card.json
                  comments.jsonl
  Always ls directories first to discover exact names.

  Read commands (nested names, mirror the trello CLI; every command emits
  normalized JSON to stdout so you can pipe to jq):
    trello board list                       # the boards the mount lists
    trello board show <board-id>
    trello board members <board-id>
    trello list list <board-id>             # lists on a board
    trello label list <board-id>
    trello card list <list-id>              # cards in a list
    trello card show <card-id>
    trello card comments <card-id>`

export const TRELLO_WRITE_PROMPT = `  Write commands (nested names; ids are flags, and --desc / --text also
  read a file via --desc_file / --text_file, or stdin):
    trello card create --list_id <list-id> --name <name> [--desc <text>]
    trello card update --card_id <card-id> [--name <name>] [--desc <text>]
                       [--due <date>] [--closed true|false]
    trello card move --card_id <card-id> --list_id <list-id>
    trello card assign --card_id <card-id> --member_id <member-id>
    trello card label --card_id <card-id> --label_id <label-id>
    trello card unlabel --card_id <card-id> --label_id <label-id>
    trello card comment --card_id <card-id> --text <text>
    trello card comment-update --card_id <card-id> --comment_id <id>
                               --text <text>`
