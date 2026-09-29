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

import { AirtableConfigSchema } from '../../../../core/airtable/config.ts'
import { Operand, Option } from '../../../spec/types.ts'
import { CLISpec } from '../../types.ts'
import * as reads from './reads.ts'
import * as writes from './writes.ts'

const BASE_OPTION = new Option({
  long: '--base',
  type: 'str',
  required: true,
  description: 'Base ID (app...)',
})

const TABLE_OPTION = new Option({
  long: '--table',
  type: 'str',
  required: true,
  description: 'Table ID or name',
})

const FIELDS_OPTION = new Option({
  long: '--fields',
  type: 'str',
  description: 'Cell values as a JSON object keyed by field name',
})

const TYPECAST_OPTION = new Option({
  long: '--typecast',
  description: 'Let Airtable convert string values to the field types',
})

const RECORD = new Operand({ type: 'str', name: 'RECORD' })

const CREATE_EPILOG =
  'Without --fields, reads records.jsonl lines from stdin and creates one\n' +
  'record per line from its "fields"; computed fields are dropped.'

const UPDATE_EPILOG =
  'Without RECORD --fields, reads records.jsonl lines from stdin and patches\n' +
  'each "record_id" with its "fields"; computed fields are dropped.'

const DELETE_EPILOG =
  'Without RECORD operands, reads records.jsonl lines from stdin and deletes\n' +
  'each "record_id".'

// The airtable program tree. Bases, tables and records are addressed by the
// ids the mount prints after the last "__" of a directory name; a write takes
// one record from flags or many as JSONL on stdin, the shape records.jsonl
// holds. Install with an AirtableConfig.
export const AIRTABLE = new CLISpec({
  name: 'airtable',
  description: 'Airtable Web API client',
  configModel: AirtableConfigSchema,
  subcommands: [
    new CLISpec({
      name: 'base',
      description: 'Read bases',
      subcommands: [
        new CLISpec({
          name: 'list',
          description: 'List the bases the token reaches as JSON',
          fn: reads.baseList,
        }),
        new CLISpec({
          name: 'get',
          description: 'Get one base and its tables (base.json)',
          fn: reads.baseGet,
          positional: [new Operand({ type: 'str', name: 'BASE' })],
        }),
      ],
    }),
    new CLISpec({
      name: 'table',
      description: 'Read table schemas',
      subcommands: [
        new CLISpec({
          name: 'get',
          description: "Get one table's fields and views (table.json)",
          fn: reads.tableGet,
          options: [BASE_OPTION],
          positional: [new Operand({ type: 'str', name: 'TABLE' })],
        }),
      ],
    }),
    new CLISpec({
      name: 'record',
      description: 'Read and write records',
      subcommands: [
        new CLISpec({
          name: 'list',
          description: 'List records as JSONL (records.jsonl)',
          fn: reads.recordList,
          options: [
            BASE_OPTION,
            TABLE_OPTION,
            new Option({
              long: '--view',
              type: 'str',
              description: 'View ID or name; its filter and sort apply',
            }),
            new Option({
              long: '--formula',
              type: 'str',
              description: 'Only the records this formula is true for (filterByFormula)',
            }),
            new Option({
              long: '--max-records',
              type: 'int',
              description: 'Stop after N records',
            }),
          ],
        }),
        new CLISpec({
          name: 'get',
          description: 'Get one record as a JSONL line',
          fn: reads.recordGet,
          options: [BASE_OPTION, TABLE_OPTION],
          positional: [RECORD],
        }),
        new CLISpec({
          name: 'create',
          description: 'Create records from --fields or stdin',
          fn: writes.recordCreate,
          write: true,
          options: [BASE_OPTION, TABLE_OPTION, FIELDS_OPTION, TYPECAST_OPTION],
          epilog: CREATE_EPILOG,
        }),
        new CLISpec({
          name: 'update',
          description: "Update records' cells (PATCH) from RECORD --fields or stdin",
          fn: writes.recordUpdate,
          write: true,
          options: [BASE_OPTION, TABLE_OPTION, FIELDS_OPTION, TYPECAST_OPTION],
          positional: [RECORD],
          epilog: UPDATE_EPILOG,
        }),
        new CLISpec({
          name: 'delete',
          description: 'Delete records by RECORD or from stdin',
          fn: writes.recordDelete,
          write: true,
          options: [BASE_OPTION, TABLE_OPTION],
          rest: RECORD,
          epilog: DELETE_EPILOG,
        }),
      ],
    }),
    new CLISpec({
      name: 'comment',
      description: 'Read and add record comments',
      subcommands: [
        new CLISpec({
          name: 'list',
          description: "List a record's comments, newest first",
          fn: reads.commentList,
          options: [BASE_OPTION, TABLE_OPTION],
          positional: [RECORD],
        }),
        new CLISpec({
          name: 'add',
          description: 'Comment on a record',
          fn: writes.commentAdd,
          write: true,
          options: [
            BASE_OPTION,
            TABLE_OPTION,
            new Option({
              long: '--text',
              type: 'str',
              description: 'Comment text (or pipe via stdin)',
            }),
          ],
          positional: [RECORD],
        }),
      ],
    }),
  ],
})
