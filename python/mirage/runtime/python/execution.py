# ========= Copyright 2026 @ Strukto.AI All Rights Reserved. =========
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ========= Copyright 2026 @ Strukto.AI All Rights Reserved. =========

PAYLOAD_ARGV0 = "-c"
STDIN_ARGV0 = "-"
STDIN_FILENAME = "<stdin>"


def prepare_source(code: str,
                   prog: str | None,
                   *,
                   script_cli: bool = False,
                   stdin: bytes | None = None) -> str:
    """Wrap a program so a `-c` subprocess reports the right argv[0].

    The subprocess tiers hand CPython the program through `-c`, because
    the source comes off a mount and may not exist on the host at all.
    CPython then hardcodes argv[0] to "-c" and names every frame
    "<string>", which is right for a payload and wrong for the other
    three doors: a script must see its own path in argv[0] and its own
    name in a traceback.

    Re-compiling under the real name fixes both at once, and the two
    preamble lines bind no names (`__import__` is called, not imported)
    and exec into `globals()`, which is `__main__`'s own dict, so the
    program runs in the module identity CPython would have given it.

    Deliberate divergence: the preamble is itself a frame, so a
    traceback carries one extra `File "<string>", line 2` line above
    the program's own. The frame that names the error is correct, which
    is the one that matters; removing the outer frame would mean
    catching and re-raising every exception, which would bind names in
    the program's namespace and rewrite `__context__`.

    Args:
        code (str): the program's source.
        prog (str | None): argv[0] for this run, as the source mode
            resolved it. None or "-c" means a payload, which CPython
            already reports correctly and which passes through
            untouched.
        script_cli (bool): bind the portable script-CLI globals.
        stdin (bytes | None): the CLI's input, without consuming sys.stdin.
    """
    if not script_cli and (prog is None or prog == PAYLOAD_ARGV0):
        return code
    # "" (piped in with no operand) and "-" (the explicit operand) are
    # both <stdin> to CPython, which reports the door rather than a
    # path because there is no file to name.
    filename = (STDIN_FILENAME
                if prog in ("", STDIN_ARGV0) else prog or '<string>')
    input_source = ("None" if stdin is None else
                    "__import__('sys').stdin.buffer.read()")
    bindings = (
        "argv = list(__import__('sys').argv)\n"
        f"stdin = {input_source}\n"
        "__import__('sys').stdin = __import__('io').TextIOWrapper("
        "__import__('io').BytesIO(stdin or b''), "
        "encoding=__import__('sys').stdin.encoding, "
        "errors=__import__('sys').stdin.errors)\n") if script_cli else ""
    argv0 = prog if prog is not None else PAYLOAD_ARGV0
    return (f"__import__('sys').argv[0] = {argv0!r}\n"
            f"{bindings}"
            f"exec(compile({code!r}, {filename!r}, 'exec'), globals())\n")
