std.open = (path, mode) => {
  const fd = __mirage_open(String(path), String(mode === undefined ? 'r' : mode))
  if (fd === -2) throw new TypeError('invalid file mode')
  if (fd < 0) return null
  // A chunked file holds one chunk of its bytes: fill until the read it is
  // about to answer lacks nothing (a negative size asks for the rest).
  const fill = (size) => {
    while (__mirage_lacks(fd, size)) __mirage_fill(fd, size)
  }
  return {
    readAsString: (max) => {
      const size = max === undefined ? -1 : toIndex(max)
      fill(size)
      return __mirage_read(fd, size)
    },
    read: () => {
      fill(-1)
      return __mirage_read(fd, -1)
    },
    getline: () => {
      while (__mirage_lacks_line(fd)) __mirage_fill(fd, 0)
      return __mirage_getline(fd)
    },
    puts: (s) => {
      __mirage_write(fd, String(s))
    },
    write: (s) => {
      __mirage_write(fd, String(s))
      return String(s).length
    },
    seek: (offset, whence) => {
      __mirage_seek(fd, offset | 0, whence === undefined ? 0 : whence | 0)
      return 0
    },
    tell: () => __mirage_tell(fd),
    eof: () => {
      fill(1)
      return __mirage_eof(fd)
    },
    flush: () => undefined,
    close: () => {
      __mirage_close(fd)
      return 0
    },
  }
}
// qjs reads a byte budget through JS_ToIndex: NaN is 0, and a negative
// or unsafe count is a RangeError.
const toIndex = (value) => {
  const n = Math.trunc(Number(value)) || 0
  if (n < 0 || n > Number.MAX_SAFE_INTEGER) throw new RangeError('invalid array index')
  return n
}
globalThis.os = globalThis.os || {}
os.readdir = (path) => __mirage_readdir(String(path))
os.stat = (path) => __mirage_stat(String(path))
os.remove = (path) => __mirage_remove(String(path))
os.mkdir = (path) => __mirage_mkdir(String(path))
os.rename = (a, b) => __mirage_rename(String(a), String(b))
os.utimes = (path, atime, mtime) => __mirage_utimes(String(path), atime, mtime)
os.S_IFMT = 61440
os.S_IFDIR = 16384
os.S_IFCHR = 8192
os.S_IFREG = 32768
os.S_IFLNK = 40960

os.getcwd = () => [__mirage_getcwd(), 0]
os.chdir = (path) => __mirage_chdir(String(path))
