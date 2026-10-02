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

export const READ_VALUE_LETTERS = new Set(['a', 'd', 'n', 'N', 't', 'p', 'i', 'u'])

// The usage line bash prints under an option error.
export const READ_USAGE =
  'read: usage: read [-ers] [-a array] [-d delim] [-i text] [-n nchars] ' +
  '[-N nchars] [-p prompt] [-t timeout] [-u fd] [name ...]\n'
