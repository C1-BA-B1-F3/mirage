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

import { VERSION } from '@struktoai/mirage-core/version'
import type { Workspace } from '@struktoai/mirage-core/workspace/workspace/workspace'
import { createSdkMcpServer, tool } from '@anthropic-ai/claude-agent-sdk'
import { z } from 'zod'
import { MirageToolOperations, type MirageToolOperationsOptions } from '../tool_operations.ts'
import {
  EDIT_DESCRIPTION,
  EDIT_INPUT,
  GLOB_DESCRIPTION,
  GLOB_INPUT,
  GREP_DESCRIPTION,
  GREP_INPUT,
  LS_DESCRIPTION,
  LS_INPUT,
  READ_DESCRIPTION,
  READ_INPUT,
  SHELL_DESCRIPTION,
  SHELL_INPUT,
  WRITE_DESCRIPTION,
  WRITE_INPUT,
} from '../tool_descriptions.ts'

/**
 * The SDK takes zod shapes, so each one restates its tool's input schema
 * from `tool_descriptions`, descriptions read off the same constants.
 */
export function MirageServer(workspace: Workspace, options: MirageToolOperationsOptions = {}) {
  const operations = new MirageToolOperations(workspace, options)
  const read = READ_INPUT.properties
  const edit = EDIT_INPUT.properties
  return createSdkMcpServer({
    name: 'mirage',
    version: VERSION,
    alwaysLoad: true,
    tools: [
      tool(
        'shell',
        SHELL_DESCRIPTION,
        { command: z.string().describe(SHELL_INPUT.properties.command.description) },
        (args) => operations.shell(args.command),
      ),
      tool(
        'read',
        READ_DESCRIPTION,
        {
          path: z.string().describe(read.path.description),
          offset: z.number().int().min(0).optional().describe(read.offset.description),
          limit: z.number().int().min(1).optional().describe(read.limit.description),
        },
        (args) => operations.read(args.path, args.offset, args.limit),
        { annotations: { readOnlyHint: true } },
      ),
      tool(
        'write',
        WRITE_DESCRIPTION,
        {
          path: z.string().describe(WRITE_INPUT.properties.path.description),
          content: z.string().describe(WRITE_INPUT.properties.content.description),
        },
        (args) => operations.write(args.path, args.content),
      ),
      tool(
        'edit',
        EDIT_DESCRIPTION,
        {
          path: z.string().describe(edit.path.description),
          old_string: z.string().describe(edit.old_string.description),
          new_string: z.string().describe(edit.new_string.description),
          replace_all: z.boolean().optional().describe(edit.replace_all.description),
        },
        (args) => operations.edit(args.path, args.old_string, args.new_string, args.replace_all),
      ),
      tool(
        'ls',
        LS_DESCRIPTION,
        { path: z.string().describe(LS_INPUT.properties.path.description) },
        (args) => operations.ls(args.path),
        { annotations: { readOnlyHint: true } },
      ),
      tool(
        'grep',
        GREP_DESCRIPTION,
        {
          pattern: z.string().describe(GREP_INPUT.properties.pattern.description),
          path: z.string().describe(GREP_INPUT.properties.path.description),
        },
        (args) => operations.grep(args.pattern, args.path),
        { annotations: { readOnlyHint: true } },
      ),
      tool(
        'glob',
        GLOB_DESCRIPTION,
        {
          pattern: z.string().describe(GLOB_INPUT.properties.pattern.description),
          path: z.string().optional().describe(GLOB_INPUT.properties.path.description),
        },
        (args) => operations.glob(args.pattern, args.path),
        { annotations: { readOnlyHint: true } },
      ),
    ],
  })
}
