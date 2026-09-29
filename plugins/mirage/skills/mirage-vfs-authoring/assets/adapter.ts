import {
  Accessor, BaseVFS, FileStat, FileType, PathSpec, VFSAdapter, Workspace,
  checkReadContract, eisdir, enoent, enotdir,
} from '@struktoai/mirage-node'

const enc = new TextEncoder()

class ResourceClient extends Accessor {
  readonly files = new Map([['hello.txt', enc.encode('Hello from my resource!\n')]])
}

async function readBytes(client: ResourceClient, path: PathSpec): Promise<Uint8Array> {
  const key = path.vfsPath.replace(/^\/+|\/+$/g, '')
  if (key === '') throw eisdir(path)
  const data = client.files.get(key)
  if (data === undefined) throw enoent(path)
  return data
}

async function readdir(client: ResourceClient, path: PathSpec): Promise<string[]> {
  if (path.vfsPath.replace(/^\/+|\/+$/g, '') !== '') {
    await readBytes(client, path)
    throw enotdir(path)
  }
  return [...client.files.keys()].sort().map(name => `${path.virtual.replace(/\/+$/, '')}/${name}`)
}

async function stat(client: ResourceClient, path: PathSpec): Promise<FileStat> {
  const name = path.virtual.replace(/\/+$/, '').split('/').pop() || '/'
  if (path.vfsPath.replace(/^\/+|\/+$/g, '') === '') return new FileStat({ name, type: FileType.DIRECTORY })
  const data = await readBytes(client, path)
  return new FileStat({ name, type: FileType.FILE, size: data.length })
}

export const adapter = new VFSAdapter({ read: { readdir, readBytes, stat } })

async function main(): Promise<void> {
  const client = new ResourceClient()
  await checkReadContract(adapter, client, {
    file: new PathSpec({ virtual: '/resource/hello.txt', directory: '/resource', vfsPath: 'hello.txt' }),
    directory: new PathSpec({ virtual: '/resource', directory: '/', vfsPath: '' }),
    missing: new PathSpec({ virtual: '/resource/missing', directory: '/resource', vfsPath: 'missing' }),
    content: enc.encode('Hello from my resource!\n'),
  })
  const ws = new Workspace({ '/resource': new BaseVFS({ name: 'resource', accessor: client, io: adapter }) })
  try {
    const result = await ws.shell('cat /resource/hello.txt')
    if (result.exitCode !== 0) throw new Error('starter mount failed')
  } finally {
    await ws.close()
  }
}

await main()
