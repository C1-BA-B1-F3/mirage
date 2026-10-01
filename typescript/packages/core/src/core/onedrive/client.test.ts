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

import { describe, expect, it } from 'vitest'

import { OneDriveAccessor } from '../../accessor/onedrive.ts'
import { driveBase, driveRefPath, itemUrl } from './client.ts'

const API = 'https://graph.microsoft.com/v1.0'

describe('OneDrive addressing', () => {
  it.each([
    [{}, `${API}/me/drive`],
    [{ driveId: 'b!drive' }, `${API}/drives/b!drive`],
    [{ siteId: 'site' }, `${API}/sites/site/drive`],
    [{ groupId: 'grp123' }, `${API}/groups/grp123/drive`],
    [{ userId: 'usr@example.com' }, `${API}/users/usr%40example.com/drive`],
    [{ userId: 'guest_x.com#EXT#@y.com' }, `${API}/users/guest_x.com%23EXT%23%40y.com/drive`],
    [{ graphBaseUrl: 'http://127.0.0.1:8080/v1.0/' }, 'http://127.0.0.1:8080/v1.0/me/drive'],
  ])('addresses %o at %s', (target, base) => {
    expect(driveBase(new OneDriveAccessor({ accessToken: 'token', ...target }).config)).toBe(base)
  })

  it.each([
    ['', '', `${API}/drives/drive/root:/team%20docs`],
    ['a b.txt', '/content', `${API}/drives/drive/root:/team%20docs/a%20b.txt:/content`],
  ])('places %j under the keyPrefix', (path, action, url) => {
    const accessor = new OneDriveAccessor({
      accessToken: 'token',
      driveId: 'drive',
      keyPrefix: '/team docs/',
    })
    expect(itemUrl(accessor.config, path, action)).toBe(url)
  })

  it('spells a ref path off the configured service root', () => {
    const accessor = new OneDriveAccessor({
      accessToken: 'token',
      driveId: 'drive',
      graphBaseUrl: 'http://127.0.0.1:8080/v1.0',
    })
    expect(driveRefPath(accessor.config, 'sub/dir')).toBe('/drives/drive/root:/sub/dir')
  })
})
