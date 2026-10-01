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

import type { JsonValue } from '../../kit/typescript/index.ts'
import type { GwsState } from '../store/state.ts'
import type { Presentation, SlidePage } from '../store/types.ts'
import type { JsonObj } from '../wire/json.ts'

export function newSlide(st: GwsState, objectId?: string): SlidePage {
  return { objectId: objectId ?? st.nextId('slide'), texts: new Map() }
}

// One Page resource, shared by presentations.get and presentations.pages.get
// so the two can never render the same slide differently.
export function fmtPage(slide: SlidePage): JsonObj {
  return {
    objectId: slide.objectId,
    pageElements: [...slide.texts.entries()].map(([objectId, text]): JsonValue => ({
      objectId,
      shape: {
        shapeType: 'TEXT_BOX',
        text: { textElements: [{ textRun: { content: text, style: {} } }] },
      },
    })),
  }
}

export function fmtPresentation(pres: Presentation, id: string): JsonObj {
  return {
    presentationId: id,
    title: pres.title,
    pageSize: {
      width: { magnitude: 9144000, unit: 'EMU' },
      height: { magnitude: 6858000, unit: 'EMU' },
    },
    slides: pres.slides.map(fmtPage),
    revisionId: `rev-${String(pres.slides.length)}`,
  }
}
