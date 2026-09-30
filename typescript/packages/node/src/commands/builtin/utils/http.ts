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

import { registerInsecureFetch } from '@struktoai/mirage-core/commands/builtin/utils/http'
import { Agent, fetch as undiciFetch } from 'undici'

// curl's -k. Node's fetch takes an undici dispatcher, and an agent built with
// `rejectUnauthorized: false` connects without verifying the server's
// certificate, host name included, as curl -k does. undici's own fetch
// carries the agent, so the dispatcher always matches the fetch whatever
// undici this Node bundles. Built on first use.
let agent: Agent | null = null

registerInsecureFetch(((input: Parameters<typeof undiciFetch>[0], init?: RequestInit) => {
  agent ??= new Agent({ connect: { rejectUnauthorized: false } })
  return undiciFetch(input, { ...(init as Parameters<typeof undiciFetch>[1]), dispatcher: agent })
}) as unknown as typeof fetch)
