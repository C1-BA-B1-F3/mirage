import { makeGenericCommands } from '../generic_bind/index.ts'
import { IO } from './io.ts'
export const WANDB_COMMANDS = makeGenericCommands('wandb', IO)
