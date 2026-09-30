import {
  Accessor,
  BaseVFS,
  type CLIInvocation,
  CLISpec,
  ContentType,
  eisdir,
  enoent,
  enotdir,
  FileStat,
  FileType,
  IOResult,
  MountMode,
  Operand,
  type PathSpec,
  RuntimeVFS,
  VFSAdapter,
  Workspace,
} from "@struktoai/mirage-node";
import { strict as assert } from "node:assert";

const ENC = new TextEncoder();

class NotesAccessor extends Accessor {
  readonly pages: ReadonlyMap<string, string>;

  constructor(pages: Record<string, string>) {
    super();
    this.pages = new Map(Object.entries(pages));
  }
}

function pageBytes(accessor: NotesAccessor, path: PathSpec): Uint8Array {
  const key = path.vfsPath.replace(/^\/+|\/+$/g, "");
  if (key === "") throw eisdir(path);
  if (key.includes("/") && accessor.pages.has(key.split("/")[0])) {
    throw enotdir(path);
  }
  const page = accessor.pages.get(key);
  if (page === undefined) throw enoent(path);
  return ENC.encode(page);
}

async function readdir(
  accessor: NotesAccessor,
  path: PathSpec,
): Promise<string[]> {
  if (path.vfsPath.replace(/^\/+|\/+$/g, "") !== "") {
    pageBytes(accessor, path);
    throw enotdir(path);
  }
  const parent = path.virtual.replace(/\/+$/, "");
  return [...accessor.pages.keys()].sort().map((name) => `${parent}/${name}`);
}

async function readBytes(
  accessor: NotesAccessor,
  path: PathSpec,
): Promise<Uint8Array> {
  return pageBytes(accessor, path);
}

async function stat(
  accessor: NotesAccessor,
  path: PathSpec,
): Promise<FileStat> {
  const name = path.virtual.replace(/\/+$/, "").split("/").pop() || "/";
  if (path.vfsPath.replace(/^\/+|\/+$/g, "") === "") {
    return new FileStat({ name, type: FileType.DIRECTORY, size: null });
  }
  return new FileStat({
    name,
    type: FileType.FILE,
    content: ContentType.TEXT,
    size: pageBytes(accessor, path).length,
  });
}

/** A flat, read-only collection of UTF-8 pages. */
class NotesVFS extends BaseVFS<NotesAccessor> {
  constructor(pages: Record<string, string>) {
    super({
      name: "notes",
      accessor: new NotesAccessor(pages),
      io: new VFSAdapter({ read: { readdir, readBytes, stat } }),
      prompt: "Read-only notes rendered as UTF-8 text files.",
      sizesAlwaysKnown: true,
    });
  }
}

async function noteInfo(inv: CLIInvocation): Promise<[Uint8Array, IOResult]> {
  const doors = inv.doors;
  if (
    doors?.dispatch === undefined ||
    doors.ns?.mounts == null ||
    doors.sessionView === undefined
  ) {
    throw new Error("note-info needs workspace doors");
  }
  const path = inv.paths[0];
  const target = doors.ns.links?.resolve(path.virtual) ?? path.virtual;
  const [data, result] = await doors.dispatch("read", path);
  if (result.exitCode !== 0) return [new Uint8Array(), result];
  if (!(data instanceof Uint8Array)) throw new TypeError("expected file bytes");
  const mount = doors.ns.mounts.rootOf(target);
  const reader = doors.sessionView.get("READER") || "anonymous";
  const header = ENC.encode(
    `mount=${mount} reader=${reader} bytes=${data.length}\n`,
  );
  const output = new Uint8Array(header.length + data.length);
  output.set(header);
  output.set(data, header.length);
  return [output, result];
}

async function show(ws: Workspace, line: string): Promise<void> {
  const result = await ws.shell(line);
  if (result.exitCode !== 0) throw new Error(`${line}: ${result.stderrText}`);
  process.stdout.write(`$ ${line}\n${result.stdoutText}`);
}

async function main(): Promise<void> {
  const ws = new Workspace(
    {
      "/notes": new NotesVFS({
        "welcome.txt": "Hello, café.\n",
        "todo.txt": "Review the BaseVFS adapter.\n",
      }),
      "/notes/status": new NotesVFS({ "health.txt": "ok\n" }),
    },
    { mode: MountMode.WRITE },
  );
  try {
    ws.registerCli(
      "note-info",
      new CLISpec({
        name: "note-info",
        positional: [
          new Operand({ name: "path", type: "path", required: true }),
        ],
        fn: noteInfo,
      }),
    );
    for (const line of [
      "ln -s /notes/welcome.txt /latest",
      "ls -1 /notes",
      "cat /latest",
      "grep BaseVFS /notes/todo.txt",
      "export READER=demo; note-info /latest",
      "note-info /notes/status/health.txt",
    ]) {
      await show(ws, line);
    }

    const expected = ENC.encode("Hello, café.\n");
    assert.deepEqual(await ws.vfs.readFile("/latest"), expected);
    assert.equal((await ws.vfs.stat("/latest")).size, expected.length);
    const reader = await ws.session("reader", {
      mounts: { "/notes": MountMode.READ },
    });
    assert.deepEqual(await reader.vfs.readFile("/latest"), expected);

    const runtime = new RuntimeVFS((op, path) => ws.dispatch(op, path));
    assert.deepEqual(await runtime.read("/latest"), expected);
    assert.equal((await runtime.stat("/latest")).isDir, false);
    const refused = await ws.shell("echo changed > /notes/welcome.txt");
    assert.notEqual(refused.exitCode, 0);
    assert.deepEqual(await ws.vfs.readFile("/latest"), expected);
    console.log(
      "Filesystem, session and runtime views agree; writes are refused.",
    );
  } finally {
    await ws.close();
  }
}

await main();
