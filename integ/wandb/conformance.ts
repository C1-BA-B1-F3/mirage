import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { startWandb } from '../server/wandb/fake.ts'
import { API_KEY } from '../server/wandb/store.ts'
import { checkSchema } from './schema.ts'

function uv(args: string[], label: string, timeout: number, env = process.env): Promise<string> {
  return new Promise((resolve, reject) => {
    const child = spawn('uv', args, { env, stdio: ['ignore', 'pipe', 'pipe'] })
    let output = ''
    child.stdout.on('data', (data: Buffer) => {
      output += data.toString()
    })
    child.stderr.on('data', (data: Buffer) => {
      output += data.toString()
    })
    const timer = setTimeout(() => child.kill('SIGTERM'), timeout)
    child.on('error', (error) => {
      clearTimeout(timer)
      reject(error)
    })
    child.on('close', (code) => {
      clearTimeout(timer)
      const reason = child.killed ? `timed out after ${timeout / 1000} s` : 'failed'
      if (code !== 0) reject(new Error(`${label} ${reason}:\n${output}`))
      else resolve(output)
    })
  })
}

checkSchema()
const server = await startWandb()
try {
  for (const version of ['0.21.1', '0.29.0']) {
    const start = server.requests.length
    const requirements = fileURLToPath(new URL(`./requirements-${version}.txt`, import.meta.url))
    const script = fileURLToPath(new URL('./sdk.py', import.meta.url))
    const run = [
      'run',
      '--isolated',
      '--no-project',
      '--python',
      '3.12',
      '--with-requirements',
      requirements,
    ]
    await uv([...run, 'python', '-I', '-c', ''], `W&B SDK ${version} install`, 300000)
    const output = await uv(
      [...run, '--offline', 'python', '-I', script],
      `W&B SDK ${version}`,
      120000,
      {
        ...process.env,
        WANDB_BASE_URL: server.base,
        WANDB_API_KEY: API_KEY,
        MIRAGE_WANDB_SDK_VERSION: version,
        WANDB_CONSOLE: 'off',
      },
    )
    assert(output.includes('"status": "passed"'), output)
    for (const line of output.split('\n'))
      if (line.startsWith('Known upstream') || line.startsWith('{')) console.log(line)
    assert.deepEqual(
      server.requests.slice(start).filter((request) => request.errors?.length),
      [],
      `SDK ${version} must not silently fall back after GraphQL failures`,
    )
  }
} finally {
  await server.close()
}
