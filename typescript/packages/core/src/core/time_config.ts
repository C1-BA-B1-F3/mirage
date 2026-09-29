import { z } from 'zod'
import { parseTime } from './time_range.ts'

const timestamp = z
  .string()
  .superRefine((value, ctx) => {
    try {
      parseTime(value)
    } catch (error) {
      ctx.addIssue({
        code: 'custom',
        message: error instanceof Error ? error.message : String(error),
      })
    }
  })
  .nullable()

export const timeRangeShape = { startTime: timestamp.optional(), endTime: timestamp.optional() }

export function orderedTimes(config: {
  startTime?: string | null | undefined
  endTime?: string | null | undefined
}): boolean {
  return (
    config.startTime == null ||
    config.endTime == null ||
    Date.parse(config.startTime) < Date.parse(config.endTime)
  )
}

export const timeRangeOrderError = { message: 'start_time must be earlier than end_time' }
