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

from mirage.commands.cli.builtin.airtable import reads, writes
from mirage.commands.cli.types import CLISpec
from mirage.commands.spec.types import Operand, Option
from mirage.core.airtable.config import AirtableConfig

BASE_OPTION = Option(long="--base",
                     type="str",
                     required=True,
                     description="Base ID (app...)")

TABLE_OPTION = Option(long="--table",
                      type="str",
                      required=True,
                      description="Table ID or name")

FIELDS_OPTION = Option(long="--fields",
                       type="str",
                       description="Cell values as a JSON object keyed by "
                       "field name")

TYPECAST_OPTION = Option(long="--typecast",
                         description="Let Airtable convert string values to "
                         "the field types")

RECORD = Operand(type="str", name="RECORD")

CREATE_EPILOG = ("Without --fields, reads records.jsonl lines from stdin "
                 "and creates one\nrecord per line from its \"fields\"; "
                 "computed fields are dropped.")

UPDATE_EPILOG = ("Without RECORD --fields, reads records.jsonl lines from "
                 "stdin and patches\neach \"record_id\" with its "
                 "\"fields\"; computed fields are dropped.")

DELETE_EPILOG = ("Without RECORD operands, reads records.jsonl lines from "
                 "stdin and deletes\neach \"record_id\".")

# The airtable program tree. Bases, tables and records are addressed by
# the ids the mount prints after the last "__" of a directory name; a
# write takes one record from flags or many as JSONL on stdin, the shape
# records.jsonl holds. Install with an AirtableConfig.
AIRTABLE = CLISpec(
    name="airtable",
    description="Airtable Web API client",
    config_model=AirtableConfig,
    subcommands=(
        CLISpec(
            name="base",
            description="Read bases",
            subcommands=(
                CLISpec(
                    name="list",
                    description="List the bases the token reaches as JSON",
                    fn=reads.base_list,
                ),
                CLISpec(
                    name="get",
                    description="Get one base and its tables (base.json)",
                    fn=reads.base_get,
                    positional=(Operand(type="str", name="BASE"), ),
                ),
            ),
        ),
        CLISpec(
            name="table",
            description="Read table schemas",
            subcommands=(CLISpec(
                name="get",
                description="Get one table's fields and views (table.json)",
                fn=reads.table_get,
                options=(BASE_OPTION, ),
                positional=(Operand(type="str", name="TABLE"), ),
            ), ),
        ),
        CLISpec(
            name="record",
            description="Read and write records",
            subcommands=(
                CLISpec(
                    name="list",
                    description="List records as JSONL (records.jsonl)",
                    fn=reads.record_list,
                    options=(
                        BASE_OPTION,
                        TABLE_OPTION,
                        Option(long="--view",
                               type="str",
                               description="View ID or name; its filter "
                               "and sort apply"),
                        Option(long="--formula",
                               type="str",
                               description="Only the records this formula "
                               "is true for (filterByFormula)"),
                        Option(long="--max-records",
                               type="int",
                               description="Stop after N records"),
                    ),
                ),
                CLISpec(
                    name="get",
                    description="Get one record as a JSONL line",
                    fn=reads.record_get,
                    options=(BASE_OPTION, TABLE_OPTION),
                    positional=(RECORD, ),
                ),
                CLISpec(
                    name="create",
                    description="Create records from --fields or stdin",
                    fn=writes.record_create,
                    write=True,
                    options=(BASE_OPTION, TABLE_OPTION, FIELDS_OPTION,
                             TYPECAST_OPTION),
                    epilog=CREATE_EPILOG,
                ),
                CLISpec(
                    name="update",
                    description="Update records' cells (PATCH) from "
                    "RECORD --fields or stdin",
                    fn=writes.record_update,
                    write=True,
                    options=(BASE_OPTION, TABLE_OPTION, FIELDS_OPTION,
                             TYPECAST_OPTION),
                    positional=(RECORD, ),
                    epilog=UPDATE_EPILOG,
                ),
                CLISpec(
                    name="delete",
                    description="Delete records by RECORD or from stdin",
                    fn=writes.record_delete,
                    write=True,
                    options=(BASE_OPTION, TABLE_OPTION),
                    rest=RECORD,
                    epilog=DELETE_EPILOG,
                ),
            ),
        ),
        CLISpec(
            name="comment",
            description="Read and add record comments",
            subcommands=(
                CLISpec(
                    name="list",
                    description="List a record's comments, newest first",
                    fn=reads.comment_list,
                    options=(BASE_OPTION, TABLE_OPTION),
                    positional=(RECORD, ),
                ),
                CLISpec(
                    name="add",
                    description="Comment on a record",
                    fn=writes.comment_add,
                    write=True,
                    options=(
                        BASE_OPTION,
                        TABLE_OPTION,
                        Option(long="--text",
                               type="str",
                               description="Comment text (or pipe via "
                               "stdin)"),
                    ),
                    positional=(RECORD, ),
                ),
            ),
        ),
    ),
)
