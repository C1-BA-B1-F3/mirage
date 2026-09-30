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

// One payload layout, shared by both languages and never versioned: a row
// is the JSON IndexEntry / IndexDirectory writes, and a row that does not
// parse is an error, not a miss. Earlier layouts are not read; flush the key
// prefix when upgrading workers that share an index.
export const ENTRY_PREFIX = 'mirage:idx:entry:'
export const CHILDREN_PREFIX = 'mirage:idx:directory:'
export const TOMBSTONE_PREFIX = 'mirage:idx:tombstone:'

export const PATHS_KEY = 'mirage:idx:paths'

export const GENERATION_KEY = 'mirage:idx:generation'

export const DEFAULT_KEY_PREFIX = 'mirage:index:'
