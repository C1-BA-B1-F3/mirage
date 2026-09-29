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

// The shell lines the MCP/REST parity run drives, and the ids they are written
// against. They live beside the fake rather than in the harness because they
// name the fixture's own pages: a fixture edit and a case edit are one change.
import { dataSourceIdOf } from './wire.ts'

const MOUNT = '/notion'
const PAGE_A = 'aaaa1111-2222-3333-4444-555566667777'
const PAGE_B = 'bbbb2222-3333-4444-5555-666677778888'
const PAGE_C = 'cccc1111-2222-3333-4444-555566667777'
const DB_TASKS = 'eeee1111-2222-3333-4444-555566667777'
const ROW_1 = 'ffff1111-2222-3333-4444-555566667777'
const DIR_A = `${MOUNT}/pages/Project_Roadmap__${PAGE_A}`
const DIR_B = `${MOUNT}/pages/Notes__${PAGE_B}`
const DIR_C = `${DIR_A}/Q1_Goals__${PAGE_C}`
const DB_DIR = `${MOUNT}/databases/Tasks__${DB_TASKS}`
// Since 2025-09-03 the rows live under the data source, not the database, so a
// row sits one level deeper than it used to. These paths feed the MCP/REST
// parity battery, where a stale one costs nothing visible: both arms answer
// the same error and the case passes while asserting nothing.
const DS_DIR = `${DB_DIR}/Tasks__${dataSourceIdOf(DB_TASKS)}`
const ROW_1_DIR = `${DS_DIR}/Write_spec__${ROW_1}`

export const CASES: ReadonlyArray<readonly [string, string]> = [
  ['ls_root', `ls ${MOUNT}/`],
  ['ls_pages', `ls ${MOUNT}/pages/`],
  ['ls_l_pages', `ls -l ${MOUNT}/pages/`],
  ['ls_page_a', `ls ${DIR_A}/`],
  ['stat_dir_a', `stat -c '%n %y' ${DIR_A}`],
  ['cat_page_a', `cat ${DIR_A}/page.json`],
  ['cat_child', `cat ${DIR_C}/page.json`],
  ['jq_title', `jq ".title" ${DIR_A}/page.json`],
  ['jq_markdown', `jq ".markdown" ${DIR_B}/page.json`],
  ['head_4', `head -n 4 ${DIR_A}/page.json`],
  ['wc_l_two', `wc -l ${DIR_A}/page.json ${DIR_B}/page.json`],
  ['stat_page_json', `stat ${DIR_A}/page.json`],
  ['find_json', `find ${MOUNT}/pages/ -name page.json`],
  ['find_root_maxdepth0', `find ${MOUNT} -maxdepth 0`],
  ['find_root_name', `find ${MOUNT} -name notion`],
  ['pipe_grep', `cat ${DIR_B}/page.json | grep -c alpha`],
  ['grep_file', `grep -n alpha ${DIR_B}/page.json`],
  ['grep_multi', `grep -c alpha ${DIR_A}/page.json ${DIR_B}/page.json`],
  ['grep_recursive', `grep -rl alpha ${MOUNT}/pages/`],
  ['realpath_dotdot', `realpath -e ${DIR_C}/../page.json`],
  ['ls_databases', `ls ${MOUNT}/databases/`],
  ['ls_database_dir', `ls ${DB_DIR}/`],
  ['cat_database_json', `cat ${DB_DIR}/database.json`],
  ['ls_data_source_dir', `ls ${DS_DIR}/`],
  ['cat_data_source_json', `cat ${DS_DIR}/data_source.json`],
  ['jq_data_source_props', `jq ".properties | keys" ${DS_DIR}/data_source.json`],
  ['cat_rows_jsonl', `cat ${DS_DIR}/rows.jsonl`],
  ['jq_rows_paths', `jq -r ".path" ${DS_DIR}/rows.jsonl`],
  ['find_data_source_dir', `find ${DS_DIR}`],
  ['ls_row_dir', `ls ${ROW_1_DIR}/`],
  ['stat_row_dir', `stat -c '%n %F' ${ROW_1_DIR}`],
  ['cat_row', `cat ${ROW_1_DIR}/page.json`],
  ['jq_row_cells', `jq ".properties.Priority.number" ${ROW_1_DIR}/page.json`],
  ['du_pages', `du ${MOUNT}/pages/`],
  ['du_page_a', `du ${DIR_A}/`],
]

export const EXIT_CODE_CASES: ReadonlyArray<readonly [string, string]> = [
  ['grep_c_match_exit', `grep -c alpha ${DIR_B}/page.json`],
  ['grep_c_no_match_exit', `grep -c zzz ${DIR_B}/page.json`],
  ['grep_rc_no_match_exit', `grep -rc zzz ${MOUNT}/pages/`],
]
