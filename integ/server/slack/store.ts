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

import type { C } from './config.ts'
import type { ChannelRow, FileRow, UserRow } from './wire.ts'

export interface MessageRow {
  tenant: string
  channelId: string
  ts: string
  userId: string
  text: string
  type: string
  subtype: string | null
  threadTs: string | null
  reactionsJson: string | null
  seq: number
}

// (tenant, channelId, ts) is the message's identity. The shared schema used an
// autoincrement `pk`, which cannot be scoped by tenant at all, so a write had
// to look the row up by pk after finding it by (channel, ts) anyway.
export function messageKey(tenant: string, channelId: string, ts: string) {
  return { tenant_channelId_ts: { tenant, channelId, ts } }
}

export function pinKey(tenant: string, channelId: string, ts: string) {
  return { tenant_channelId_ts: { tenant, channelId, ts } }
}

export async function channelById(db: C, tenant: string, id: string): Promise<ChannelRow | null> {
  return db.channel.findUnique({ where: { tenant_id: { tenant, id } } })
}

export async function messageAt(
  db: C,
  tenant: string,
  channelId: string,
  ts: string,
): Promise<MessageRow | null> {
  return db.message.findUnique({ where: messageKey(tenant, channelId, ts) })
}

export async function channels(db: C, tenant: string): Promise<ChannelRow[]> {
  return db.channel.findMany({ where: { tenant }, orderBy: { id: 'asc' } })
}

export async function users(db: C, tenant: string): Promise<UserRow[]> {
  return db.user.findMany({ where: { tenant }, orderBy: { id: 'asc' } })
}

export async function filesIn(db: C, tenant: string, channelId: string): Promise<FileRow[]> {
  return db.slackFile.findMany({ where: { tenant, channelId }, orderBy: { id: 'asc' } })
}

export async function fileById(db: C, tenant: string, id: string): Promise<FileRow | null> {
  return db.slackFile.findUnique({ where: { tenant_id: { tenant, id } } })
}
